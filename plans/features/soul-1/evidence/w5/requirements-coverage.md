# SOUL-1 / W5 — покрытие требований (SOUL-18.0–18.7, SOUL-05.8)

Слайс: `W5` (инициатива: диагностика отсутствующих отправок и честная
жизнеспособность). Кандидат — рабочее дерево поверх `ba258e5d` (коммитов и
деплоя нет; AUTO-статусы PENDING в карте — зона PM).

Легенда:
* `VERIFIED-BY-TEST` — контракт/поведение закрыты тестами слайса и/или
  прогоном UI-сторожа (движок, API, панель);
* `LIVE_UNVERIFIED` — требует реальной конфе/канарейки (флаги OFF по
  умолчанию); план наблюдения — `live-acceptance-plan.md`.

Источники доказательств в этой папке: `focused-tests.txt` (33 теста слайса),
`perimeter.txt` (3902 passed / 0 failed), `js-guards.txt` (4 node-сторожа),
`mutation-witness.json` (9/9 мутаций убито), `parity-off.json` (оси OFF →
паритет), `catalog-reissue.txt` (F8-переиздание каталога + `--check OK`),
`live-acceptance-plan.md`, `visual-pending.md` (закрыт ревью),
`requirements-coverage.md` (этот файл). Независимое ревью —
`plans/features/soul-1/review-w5.md` (BLOCKER-1 закрыт правкой формулировок
D1; рендер панели закрыт §2 ревью).

## SOUL-18.0 — раздел SOUL-18 в целом

| req_id | статус | доказательство |
|---|---|---|
| SOUL-18.0 | VERIFIED-BY-TEST (движок) + LIVE_UNVERIFIED (живые числа) | Воронка, диагностика, health≠outcome, мягкие цели, mock-проверка и MiniApp-панель реализованы и покрыты `focused-tests.txt`; реальные 24–48ч числа и живые сценарии — по плану наблюдения (раздел ниже) |

## SOUL-18.1 (строка источника 272) — автономия + реальные счётчики цепочки

| req_id | статус | доказательство |
|---|---|---|
| SOUL-18.2 | VERIFIED-BY-TEST (счётчики) / LIVE_UNVERIFIED (24–48ч) | `services/initiative_diagnostics.py`: оконные 24ч/48ч из durable-checkpoint (дельта накопительных counters) + события `mca_events` + ledger `mca_bot_outputs`; нули видны нулями, покрытие окна честно (`full/partial/insufficient` + `coverage_note`). Тесты: `test_empty_db_gives_zeros_and_insufficient_coverage`, `test_window_deltas_come_from_durable_counters`, `test_coverage_partial_when_history_shorter_than_window`, `test_opportunity_kinds_and_silence_reasons_distribution`, `test_sends_are_correlated_with_message_id_and_manifest` (виды поводов, решения по действиям, молчание с причинами, попытки/recheck, доставки, дубли, задержка p50/max, last-штампы). Цепочка observer→scan→opportunity→candidate/intent→decision→Writer→recheck→send проверена существующими B01/F6-тестами + новым mock-send trace (`test_check_dry_run_reaches_mock_send_without_publishing`). **Живые 24–48ч числа** (счётчики по реальной конфе, распределение причин, latency) — `LIVE_UNVERIFIED`: требуют прод-БД, см. план |

## SOUL-18.2 (строка 273) — не задушены ли возможности

| req_id | статус | доказательство |
|---|---|---|
| SOUL-18.3 | VERIFIED-BY-TEST (аудит+фиксы+негативы) / LIVE_UNVERIFIED (живая конфа) | **Найдены и исправлены: дефект состояния окна (D1), подтверждённая причина устаревания поводов (D2) и разрыв наблюдаемости причин (D3).** D1: `not_enough_messages`/`eval_not_due` сбрасывали `pending` и `last_eval_ts` — это **дефект состояния окна** (два RED→GREEN-свидетеля: `test_not_enough_keeps_pending_and_interval_stamp`, `test_eval_not_due_keeps_pending_for_later`; мутации M6/M6b); поведенческая формулировка «тихий чат не накопит порог никогда» **не подтверждена** (тик пересоздаёт durable-задачу с чистым payload — база тоже оценивала тихие чаты; репро REVIEW-W5: 3 реплики × 4 тика и 1 × 10 при пороге 8 → `evals=1`), поэтому D1 — контрактная защита на будущее, а не установленная причина тишины. D2 (главная подтверждённая причина): окно оценки бралось `ASC LIMIT 42` от начала корпуса → «хвост старой пачки»; на базе свежий маркер реплики **отсутствовал** в промпте оценки (`false` → `true` на кандидате), отставание от разговора росло без ограничения; теперь окно = самые свежие 14 элигибельных реплик + watermark (`test_window_is_the_freshest_and_watermark_catches_up`). Негативы на месте: дедуп контекста (`test_context_duplicate_still_blocks_repeat_evaluation`), пауза после реплики бота (`test_min_gap_after_bot_reply_still_blocks`), дневной лимит (`test_day_cap_still_hard_with_soft_target`), scope OFF (`test_chat_scope_off_blocks_any_evaluation`), «не та» строка — не текст/форвард/команда/без автора/личка (`test_ineligible_rows_are_skipped_with_reasons`), недоступный оценщик виден, а не молчит (`test_llm_unavailable_is_visible_not_silent`). D3: причины инициативного молчания (`default`, `recent_reply`, `l1_silent`, `l1_unavailable`, `recheck_demoted`, `delivery_not_text`, `l1_react`) ранее МОЛЧА выбрасывались контрактом событий (whitelist miss) — теперь сохраняются (`test_initiative_reason_codes_survive_event_contract`, мутация M7). **Доказательство на активной реальной конфе** — `LIVE_UNVERIFIED` (план ниже); окончательная атрибуция тишины прода — по плану наблюдения |

## SOUL-18.3 (строка 274) — владельческие мягкие цели + безопасная проверка

| req_id | статус | доказательство |
|---|---|---|
| SOUL-18.4 | VERIFIED-BY-TEST (движок/API/UI) / LIVE_UNVERIFIED (реальная отправка) | Новые ключи владельца (PG-only, группы `limits_intent`/`flags_intent`): `initiative.soft_target_replies_per_day`, `initiative.observation_target_interval_seconds` + ось `flags.initiative_diagnostics_publish_enabled` (default OFF). Мягкая цель — предпочтение, не обещание: эффект ограничен код-константами (`MIN_OBSERVATION_INTERVAL_FLOOR=600`, `MIN_EVAL_MESSAGES_FLOOR=4`, `MIN_GAP_FLOOR_SECONDS=1800`) и не ужесточает лимиты (`test_soft_targets_only_ease_within_documented_bounds`, `test_observation_target_below_floor_clamps`, мутация M5); при 0/0 — паритет профиля (`test_soft_targets_zero_keep_profile_parity`, `parity-off.json`). Настройка по чату — существующий механизм `chat_params` override → hot → дефолт, действующие значения и источник видны в `gates.effective`/`gates.soft_targets`. Real-time причины отказов — `initiative_observer.chat_block_state` (12 ворот с `value/limit/reason_code`, включая «живого контекста нет», лимиты, бюджет, дедуп, доступность оценщика/писателя). Безопасная проверка «Проверить инициативу»: `POST /api/memory/initiative-check` — полный trace (ворота → окно → оценка → решение → Writer → форма → recheck → mock send) БЕЗ публикации; публикация возможна только при включённой оси И `confirm_publish=true` (`test_check_dry_run_reaches_mock_send_without_publishing`, `test_check_publish_is_off_without_owner_axis`, мутация M2, UI-сторож проверяет `publish:false` по умолчанию). Реальная send-проверка и живое подтверждение — `LIVE_UNVERIFIED` (отдельное действие владельца) |

## SOUL-18.4 (строка 275) — health отдельно от outcome

| req_id | статус | доказательство |
|---|---|---|
| SOUL-18.5 | VERIFIED-BY-TEST | `initiative_diagnostics.activity_verdict` отделяет техническое здоровье от доставки: `opportunities_no_messages` — предупреждение «Возможности есть, сообщений нет» с распределением причин и рекомендацией (`test_opportunities_without_messages_is_a_warning`, мутация M1); `observer_silent_live_chat` — при 0 возможностей и 2000+ живых сообщениях (диагностируется scope/порог/пауза, а не «healthy»; `test_live_chat_without_opportunities_is_diagnosed`); `low_activity` — низкая естественная активность не ошибка (`test_low_activity_is_not_an_error`); `disabled` — выключенные ворота называются причиной (`test_disabled_scope_is_reported_not_hidden`); `no_data` — честное отсутствие данных. `health.note` фиксирует «heartbeat≠outcome: тики и прогоны не являются отправкой»; `jobs_processed`/`heartbeat_ok` никогда не подменяют `delivered` |

## SOUL-18.5 (строка 276) — MiniApp: одно место, message_id + Core/Style, hard-форма

| req_id | статус | доказательство |
|---|---|---|
| SOUL-18.6 | VERIFIED (движок/API/UI; рендер панели подтверждён независимым ревью — Playwright + Browser Use на реальном Chrome, `review-w5.md` §2) / LIVE_UNVERIFIED (реальные доставки) | В Статусе — ТА ЖЕ единственная панель (`data-initiative-independent`, ровно один якорь; второй стены/страницы/пункта навигации нет — node-сторож `soul1_w5_initiative_panel_test.js`). В панели: предупреждение health≠outcome, health-строка с числом отправок, мягкие цели с границами, распределение причин, «мешает сейчас», последние решения/отказы, доставленные сообщения с `message_id` + ревизиями Core/Style/composer, кнопка и trace проверки. Сопоставление доставки с манифестом — новое событие `initiative_delivery_manifest` (ревизии `core/style/identity/manifest/composer` в `entity_ids`+`config_version`, пишется ПОСЛЕ подтверждённой доставки; `test_sends_are_correlated_with_message_id_and_manifest`: доставка без манифеста честно показывает «нет данных», а не текущие значения). Инициатива отдельно проверена: hard no-quotes/no-trailing-period тем же единственным проходом формы (`test_initiative_text_goes_through_single_style_pass`) и `one_word`/`micro` — extent L1 доходит до прохода (`test_initiative_style_pass_receives_l1_extent`). Счётчик панели всегда читается из одного диагностического endpoint (`/api/memory/initiative-vitality`, RBAC global admin, 401/403 проверены) |

## SOUL-18.6 (строка 277) — live acceptance

| req_id | статус | доказательство |
|---|---|---|
| SOUL-18.7 | LIVE_UNVERIFIED | Ни одной искусственной отправки в рабочую группу не сделано (это прямо запрещено требованием). План наблюдения 24–48ч: `live-acceptance-plan.md` (флаги OFF; канарейка позже; критерии SILENT/REACT/короткая реплика/связанный абсурд/попытка send/доставка) |

## SOUL-05.8 — Initiative = тот же Core/Composer/Writer, SILENT легален

| req_id | статус | доказательство |
|---|---|---|
| SOUL-05.8 | VERIFIED-BY-TEST | Один и тот же Core/Style/личность: `test_initiative_writer_shares_core_style_and_persona` — манифест `initiative_writer` и Direct-писателя того же чата дают равные ревизии `core`/`style_policy`/`identity`, пин хода (`recall_turn_refs`) совпадает с ревизией Core (мутация M4 убивает расхождение identity). SILENT легален и не вызывает Writer: `test_silent_decision_never_calls_writer`. Автономия от Direct сохранена: наблюдатель читает `smart_messages` напрямую, шум/лимиты ворот не подменяют Direct (негативы SOUL-18.3) |

## SOUL-19 (§20) — релевантные клаузы

| клауза | статус | доказательство |
|---|---|---|
| «инициативная воронка не подменяет отправки» | VERIFIED-BY-TEST | mock-прогон не пишет `initiative_decided`/`initiative_sent` и не создаёт записей воронки; единственный след — маркер `initiative_diagnostics_check` (`test_check_dry_run_reaches_mock_send_without_publishing`, мутация M2) |
| «output compliance валидируется на доставке» | VERIFIED-BY-TEST (движок) | проход формы применяется к инициативному тексту ровно один раз перед чанкованием/отправкой (W3-шов) + мои тесты на hard-правила и extent |
| «версии всех слоёв в run context» / «initiative send funnel» | VERIFIED-BY-TEST (движок) | `initiative_delivery_manifest` + `versions` композера + окна воронки в одном payload |

## Честные границы (не закрыто этим слайсом)

1. **Живые 24–48ч числа** по реальной конфе — `LIVE_UNVERIFIED` (нужен
   прод-доступ/канарейка): движок считает, чисел в прод-БД ещё нет.
2. **Реальная send-проверка** (ось публикации) — `LIVE_UNVERIFIED`:
   отдельное явное действие владельца, ни одного сообщения в чат не ушло.
3. **Живые сценарии §19 п.6** (SILENT/REACT/короткая реплика/абсурд/
   доставка) — `LIVE_UNVERIFIED` по плану наблюдения.
4. Предсуществующие 6 падающих тестов из аудита
   (`audit-ui-initiative-legacy-recon.md` D.6), в т.ч.
   `test_summary_publish_integration_round1026.py::TestOnDelivery::
   test_on_l1_not_usable_level2_l2_publishes_article`, — НЕ регрессия W5
   (вне периметра, воспроизводились локально до слайса; классификация
   fix/re-pin — задача владельца/D.6).
5. **Атрибуция тишины прода** — D1 (сброс `pending`/`last_eval_ts`) это
   дефект состояния окна, а не установленная причина; подтверждённая причина
   — D2 (устаревшее окно оценки). Окончательная атрибуция причин отсутствия
   инициатив — по живым числам плана наблюдения, без преждевременных
   выводов.

Закрыто независимым ревью: рендер-проверка панели (Playwright + Browser Use,
реальный Chrome) — `review-w5.md` §2, `visual-pending.md` помечен `CLOSED`.
