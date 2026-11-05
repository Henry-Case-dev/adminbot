# UR-F — UI-волна UNIFIED-REPLY + UI-half BGS-06-ADMIN: evidence

Кандидат: ветка `ur/f-ui` (base `evol/impl` @ `ebe79af6`).
Машиночитаемый отчёт: `urf-visual-report.json` (этот каталог).
Playwright-E2E: `tools/ui_urf_visual_e2e.py` (`URF-VISUAL-OK`, exit 0).
Скриншоты: Playwright `urf-*-desktop-1440.png` / `urf-*-mobile-390.png`;
Browser-Use (реальный Chrome CDP) `bu-*.png` — 10 экранов, desktop 1440×900
+ mobile 390×844, консоль браузера чиста (0 ошибок, оба прогона).

## Статус строк среза (proven / superseded / blocked)

| Требование | Статус | Доказательство |
|---|---|---|
| UR-20.1 (три уровня, mobile-first) | proven | `tests/js/ur_ui_settings_test.js` п.5 (workspace mod_direct = overview/inspector/settings); скриншоты `urf-modes-*`, `bu-inspector-*` |
| UR-20.2 («Как бот отвечает») | proven | `directModesView` из effective-config; `urf-modes-desktop-1440.png` (5 режимов со статусами) |
| UR-20.3 («Что бот видел») | proven | инспектор хода; `urf-inspector-desktop-1440.png`; `tests/js/ur_ui_settings_test.js` п.4 |
| UR-29.3 (часы хода в инспекторе) | proven | `turnClockLine` из `clock_timezone/as_of_utc` трассы; тест п.4; скриншот инспектора |
| UR-20.9 (compact advanced) | proven (частично: поиск по настройкам — существующий `configSearch`, восстановление — существующий «↪ Глобальное») | eff-бейджи/units/source на карточках; `urf-direct-limits-*` |
| UR-21.01 (CURRENT_QUESTION_MAX_CHARS) | proven | честная подпись «как лимит вопроса не редактируется»; `test_ur_ui_effective_config.py::test_renamed_rows_honest` |
| UR-21.13 / UR-14.2 (якоря из UI) | proven | `_UR_F_WITHOUT_RUNTIME_READER` hidden; API-тест `test_dead_keys_absent_from_config_and_params_meta`; визуально `deadFound=[]` в `urf-visual-report.json` |
| UR-21.15 (TTL → «История того, кому…») | proven | переименование; тест + скриншот limits |
| UR-21.17 (Response ratio no-op удалён) | proven | hidden + eff no_op с причиной; тесты |
| UR-21.19 (CONTEXT_BUDGET = рабочее окно, экспертный cap) | proven | описание; тест |
| UR-21.20 (lock waits → «Служебное») | proven | группа limits_service; тест + `urf-checkup-limits-*` |
| UR-21.21 (LOCK_MAX_ENTRIES из редактирования) | proven | hidden; тест |
| UR-21.22 (SILENCE_AFTER_COOLDOWNS = «Частота участия») | proven | переименование; тест + скриншот |
| UR-21.23 («Свобода формулировок» + пометка про temperature) | proven (display-only; рантайм-половина — BGS-05-BUDGET) | `provider_ignores_temperature` + eff reason_inactive в /api/config; `test_honest_speech_label`, `test_speech_item_carries_units_and_honest_note`; скриншоты limits/modes |
| UR-21.24 (реальная применимость, без настроек-для-настроек) | proven | `effective_meta` (no_op/legacy/active + reason_inactive); тесты; UI не добавил ни одного нового ключа |
| UR-22.1 (effective_value/source/status/…; UI не угадывает) | proven | `/api/config` отдаёт `source` (chat/global/default), `effective_value`, `eff{status,active_consumer,units,reason_inactive}`; `test_items_carry_source_effective_and_eff`; `last_applied_turn` не отдаётся — данных нет, не выдумывается (честный пробел) |
| UR-22.2 (desktop/mobile 320–430, доступность) | proven (390/1440; 320 покрыт общей адаптивностью, отдельный проход матрицы §71 — вне среза) | hScroll=false на всех 8 пробах; скриншоты mobile |
| UR-29.1 («Модули → Время»: поле+поиск+часы+наследование) | proven | `urf-time-*`; JS-тест п.1; API `test_timezones_full_iana_list`, `test_time_global_state_from_server` |
| UR-29.2 (validated effective + now_local от сервера) | proven | POST возвращает state после записи; `test_post_valid_zone_returns_validated_effective`, `test_post_invalid_zone_422_keeps_previous`; часы тикают от as_of_utc+offset (JS-тест), не от браузера |
| UR-24 (зонт; UR-24.2 UI-часть) | proven (UI-часть; 24.1/24.3/24.4 были VERIFIED в UR-C-CLOCK) | CHAT_TIMEZONE hidden; единая поверхность /api/config/time (GET/POST/DELETE) |
| BGS-06.1 (без мёртвых тумблеров, эффективное значение+источник) | proven | см. UR-14.2/21.x/22.1 |
| BGS-06.2 (группы «Поиск и инструменты»/«Речь и характер»/… ) | proven (частично: существующие группы переименованы честно; полная перегруппировка всех разделов — вне ключей UR-21/BGS-06.5) | GROUPS descriptions честные; `test_group_descriptions_not_promising_removed_mechanics` |
| BGS-06.3 (пользовательские подписи, без псевдо-IQ) | proven | «Свобода формулировок»; панели машинных флагов нет (`machineFlagsPanel=false` в отчёте) |
| BGS-06.5 (флаги: eff+source+владелец) | proven | eff/source на каждой карточке (API-тест); владелец правила — существующая матрица прав (gear-иконка) |
| BGS-06.10 (нет фейкового success; desktop=mobile) | proven | POST /api/config/time возвращает фактическое состояние после записи; ошибки 422 показываются, прежнее значение живо (`test_post_invalid_zone_422_keeps_previous`); parity скриншотов |
| R-ADM.1 (изменение отражено в UI чата) | proven (UI-часть; серверная — VERIFIED в RLR-05) | мёртвых переключателей нет; honest-нотисы |
| R-ADM.5 (диагностика одного ответа) | proven | GET /api/direct/turn-diagnostics из существующих событий `services/turn_trace.py` (L1→tools→Writer→ops→delivery, digest/divergence честно); `TestTurnDiagnostics` (5 тестов); `urf-inspector-*` |
| R-ADM.6 («Единое написание ответа» / «Техническая очистка» подписи) | proven (display-часть) | панель машинных флагов не рисуется; retained_* ключи не показываются (env-only не в каталоге UI), honest-бейджи legacy/no-op |
| R-ADM.7 (редакторы промптов и версии рабочие mobile+desktop) | proven (не редизайнились; вкладки synthesizer/verbalizer на месте — JS-тест п.5; скриншоты settings) | |

## Superseded / вне среза (честно)
* UR-21.23 рантайм-половина (сэмплинг per-model) — BGS-05-BUDGET (влита).
* UR-22.1 `last_applied_turn` — не отдаётся (нет источника данных; поле не выдумано).
* Полная трёхуровневая перегруппировка ВСЕХ разделов (не только «Прямых ответов») —
  поверхность UR-20.1 реализована для модуля Direct; остальные модули не тронуты
  (frozen visual contract).
* 320px — покрыт общей адаптивностью (grid 1-col, без h-scroll); детальная матрица
  §71 — существующий `tools/ui_round1025_matrix.py`.

## Тесты
* `tests/js/ur_ui_settings_test.js` — НОВЫЙ (UR-F-UI-OK): время/зоны/часы,
  dead-keys honesty, «Свобода формулировок», инспектор-поля, три уровня.
* `tests/test_ur_ui_effective_config.py` — НОВЫЙ, 25 passed: каталог-honesty,
  effective-config API, время (IANA/validated/422), диагностика хода.
* Пины меню обновлены с санкционированной Δ UR-F (+mod_time, noToggle):
  round1020_ui_rework, round1020_ui, round1021_ui_audit, round1024_budget_toggle,
  round1024_image_module, round1025_f4_module_store, round1025_f5_workspace_route,
  soul1_w5_initiative_panel.
* Прогон: JS 107 pass / 2 fail (ОБА pre-existing на базе ebe79af6:
  `asap6_wave2_ux_tabs_test` — dossier-ticker в Статусе вместо Аналитики;
  `round1025_ia_routing_test` — подпись алиаса #/ai/persona). Pytest
  (param_catalog + rlr_admin_manifest + ur_c_clock + ur_ui_effective_config +
  webapp_api): 281 passed. Pre-existing: `test_chat_settings_seed_round1019::
  test_chat_id_absent_from_services` (database.py из ur-c-мержа, файл не тронут).

## Изменённые файлы
`web/app.js`, `web/index.html`, `services/param_catalog.py`,
`web/api/routes.py`, `tools/ui_urf_visual_e2e.py` (новый),
`tests/js/ur_ui_settings_test.js` (новый),
`tests/test_ur_ui_effective_config.py` (новый), 8 JS-пинов (Δ-комментарии),
`plans/features/unified-reply/evidence/urf/**` (22 скриншота + отчёт).
