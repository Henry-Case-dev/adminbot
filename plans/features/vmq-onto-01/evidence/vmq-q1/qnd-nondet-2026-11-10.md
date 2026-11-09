# QND-NONDET — evidence (owner corrective 2026-11-10)

**Slice:** smart-module-semantic-routing / QND-NONDET
**Contract (frozen, 139 строк):** `plans/features/smart-module-semantic-routing/quantum-nondeterminism-contract.md`
**Owner source:** `plans/owner_inputs/2026-11-10-quantum-nondeterminism-correction.md`
**Base:** `6674811f` **Кандидат:** `bc62da05` + `46cb550b` (тот же слайс, доводка)
**Ветка/дерево:** `integ/unify-release`, worktree `hotfix-meme-publication-initia-d78f499866ee-6ef91e44`

## 1. Что реализовано по разделам контракта

| § | Требование | Реализация |
|---|-----------|-----------|
| 1 | Пер-чатовое стохастическое расписание, durable | `services/semantic_schedule.py`; таблица `semantic_schedule` (PK `chat_id, mechanism`), миграция `_SCHEMA_VERSION_SEMANTIC_SCHEDULE = 47` (аддитивно, без backfill, PG — no-op) |
| 1 | Границы/коэффициенты — редактируемые `ParamSpec` | 32 записи `limits.qnd_*` в `services/param_catalog.py`, groups `limits_qnd` / `limits_qnd_nostalgia`, вкладки `mod_initiative` / `mod_nostalgia`; ключи собираются литералами `CADENCE_PARAMS`/`PUBLICATION_PARAMS` (аудит каталога видит каждую ручку) |
| 1 | Пропуск срока / аренда / смена настроек | `due / claim / mark_executed / mark_missed / ensure / draw_next / due_chats`; `reason_code` = `stale_deadline`, `lease_held`, `settings_rescaled`, `no_state` |
| 1 | Технический heartbeat вместо фиксированного тика | `NostalgiaWorker.start`: `limits.qnd_heartbeat_seconds`; PRNG-jitter (`random.randint`/`jitter_safe`) удалён; тик исполняет только наступившие события |
| 2 | Событийный путь без второго Observer | `handlers/summary.py` после успешного `save_live_message` → `semantic_schedule.request_event` (durable `scan_requested_at` + немедленный `TaskSupervisor` → `observe_tick(trigger="event", only_chat=…)`); `InitiativeObserverRunner.run(job_id, only_chat=…)`; дебаунс, событийный пол, `event_dropped_busy` |
| 3 | Вероятность публикации вместо двойного гейта | `services/quantum_publication.py::decide` (факторы r,s,a,t,q,n; `S`; logistic; один draw; `publish iff not deferred and u < p`); порог агрессивности и вероятностный гейт ПЕРЕД оценкой удалены; `decide()` в `_candidate_llm_send` и `_act_on_opportunity`; `silent` требует `veto_reason` из закрытого набора |
| 4 | Единственный источник случайности | `SANCTIONED_DRAW_PURPOSES` +4 purpose (`nostalgia_schedule`, `initiative_schedule`, `nostalgia_publication`, `initiative_publication`); `initiative_trigger` выведен; `_direction_pick` — взвешенный inverse-CDF по одному `u` (purpose `memory_recall`) |
| 5 | Durable-события и честные витрины | `quantum_schedule_draw/due/evaluation/publication_decision/result` (component `qnd`); `services/qnd_diagnostics.py`; блок `quantum` в `/api/status` и vitality; правило «нет квантовых значений → нет слова „работает“» + «нет данных» вместо процента без знаменателя |
| 6 | Мандатная коррекция выпущенного | (a) `_direction_pick` больше не tie-band; (b) `_candidate_llm_send` — `decide()` после LLM-вето; (c) cadence в расписании, jitter снят; (d) `recall_in_conversation` — тот же `decide()`; (e) `random_trigger` на гейте оценки убран; (f) `_next_check_ts` = `semantic_schedule.next_due_ts` |
| 7 | Тесты | `tests/test_qnd_schedule.py` (12), `test_qnd_publication.py` (5), `test_qnd_event_path.py` (4), `test_qnd_metrics.py` (3); `tests/qnd_fakes.py` (управляемый источник) |

Промпт Observer: ревизия `initiative-observer-qnd-veto` (sha12 `4bb33535bad5`),
общий factory-отпечаток переутверждён осознанно (`FACTORY_SET_SHA256_12=1532c9480cd5`).

## 2. Решающая проверка (§7, требование владельца)

`tests/test_qnd_publication.py::test_same_semantic_situation_different_quantum_values_differ`
— одинаковая семантическая ситуация и одинаковые гейты, различается только
квантовое значение: `u=0.02` → `outcome=delivered`; `u=0.98` →
`outcome=silent, silence_cause=random_miss`; обе durable-строки несут одинаковый
`p`. **Наблюдаемый результат: PASS.** Случайность не декоративна и не ограничена ничьими.

## 3. Наблюдаемые результаты прогонов (кандидат `46cb550b`, Windows, .venv)

| Набор | Команда (сокращённо) | Результат |
|-------|----------------------|-----------|
| Все QND-тесты контракта | `pytest tests/test_qnd_*.py` | **24 passed** |
| Расписание/публикация/событие/метрики + nostalgia (3) + observer (2) + vitality + memory_maintenance + initiative_coordination | 12 файлов | **196 passed, 4 failed** — все 4 падают и на базе `6674811f` |
| Random/каталог/схема/миграции/webapp (24 файла) | mca10a×5, mca10b×4, database, scheduler, communities/identity-миграции, t5150, param_catalog, frontend_tab_mapping, asap7, status_service, webapp_parity, evol014, publications API, telemetry, asap8_f6 | **552 passed, 0 failed** |
| Доводка (11 файлов: evol016, mca17c, mod_acl edges, p0_init_arch, summary l1/l2/publish, 4×QND) | | **306 passed** |
| JS-unit | `node tests/js/*.js` (113 файлов) | 8 падений — **ровно те же 8, что на базе** |

Признанные pre-existing (проверено прогоном на `6674811f` в отдельном worktree):
`test_initiative_coordination` (4), `test_unified_image_request_round1026::forbidden_paths`,
`test_tool_coordinator_round1026::forbidden_paths`, `test_mca01_...::write_points`
(дрейф allowlist), `test_prompt_field_audit`, `test_evol018_prompt_audit` (устаревшие
пиннинги), `test_speech_p0_a2_memory`, `test_summary_generator` (2),
`test_summary_two_call_round1022` (3), `test_verbilizer_response_modes_round1023` (1),
`test_cfg03_param_audit::dead_knobs` (`flags.dig_pre_gate_enabled`), webapp-навигация/
glass/js-unit (8), `test_youtube_multimodal_download_round1024` (20 errors),
`test_soul1_registry_completeness` (сдвиг указателя `lore_worker.py:709`).

## 4. Что осталось проверить реальным запуском (не автоматизируется здесь)

1. Реальный ANU: первый боевой `quantum_schedule_draw`/`quantum_publication_decision`
   с `source=quantum` (в тестах источник управляемый, провайдер недоступен).
2. Живой ритм за сутки: распределение интервалов, независимость двух чатов,
   отсутствие «одновременных» проверок.
3. Продуктовое ощущение частоты при текущих `limits.qnd_*` (правится настройками).
4. Визуальная проверка блоков «Статус»/«Аналитика» на реальных данных в браузере
   (в этой сессии Playwright/Browser Use к приложению не подключались).

## 5. Ревью-фиксы (кандидат `629743f9` поверх `0cebea92`)

Решающее свойство §7 ревью подтвердило (одна и та же ситуация, `p=0.266404`
в обеих строках, `u=0.02` → delivered, `u=0.98` → silent/`random_miss`).
Ниже — что исправлено, без изменения дизайна.

| # | Блокер | Причина | Исправление | Доказательство |
|---|--------|---------|-------------|----------------|
| B1 | Пин-тесты красные | Каталог вырос ровно на 32 записи (31 `limits.qnd_*` + compat `initiative.trigger_probability`) | `test_mca19_block_f_round1043.py`: `len(tsv)` 607→**639**, `len(REASON_CODES)` 330→**341**, мета 606/205→**638/237**; комментарии называют происхождение; ассерты не ослаблены | `pytest tests/test_mca19_block_f_round1043.py` → **10 passed** |
| B2 | Событие сдвигало срок ностальгии | `request_event` ставил `scan_requested_at` ОБОИМ механизмам, а у `NostalgiaWorker._run_chat` нет событийного гейта (он только в `initiative_observer.event_gate`) | Метка ставится только `MECH_INITIATIVE`: событийный путь принадлежит Observer (§2), а частота ностальгии — нарисованный срок | Новый тест `test_four_live_messages_in_90s_do_not_break_nostalgia_deadline`: 4 сообщения за 90 с → **0** вызовов модели, `next_due_ts` не изменён |
| B3 | Любое молчание писалось как `dedup` | `outcome=("send_recheck" if "recheck" in reason else "dedup")` | `quantum_publication.publication_result_outcome`: коды `semantic_silent`, `semantic_unavailable`, `not_text`, `reacted`, `silent_other`; `dedup` — только реальная дедупликация | Новый тест `test_silent_reasons_get_their_own_outcome_codes`: `l1_silent` → `semantic_silent`, `dedup` не появляется |
| B4 | Тест публикации зависел от монеты | Тест не подставлял управляемый источник, а `decide()` реально разыгрывает | `FakeQuantumSource(default=0.0, indices=[0])` в `test_one_llm_call_one_send` | **25/25** изолированных прогонов зелёные (было 1 падение из 25) |

Не-блокеры (в том же коммите):
* `qnd_diagnostics`: `last_draw.ts` больше не `None` — `ts` берётся из
  КОЛОНКИ события и кладётся в разобранный payload (мёртвое поле ожило);
  тест метрик это утверждает.
* Гистограмма интервалов: точное покрытие бакетов (ceil-деление,
  `min(hi, …)`), срез `[-6:]` убран → сумма `count` равна числу розыгрышей.
* Статус/Аналитика: `evaluations.schedule/event` подписаны как **решения о
  публикации** (это вызовы `decide()`; отказ модели до розыгрыша в них не
  виден) — вместо прежней подписи «Оценки».

## 6. Прогоны на кандидате `629743f9`

| Набор | Результат |
|-------|-----------|
| QND-контракт (`test_qnd_schedule/publication/event_path/metrics`) | **26 passed** (24 прежних + 2 регрессии B2/B3) |
| QND + ностальгия (3) + observer (2) + vitality + memory_maintenance + coordination | **198 passed, 4 failed** — ровно те же 4, что на базе `6674811f` |
| Random (mca10a×5, mca10b×4) + схема/миграции + каталог + webapp-parity + промпт-аудит (27 файлов) | **597 passed, 1 failed** — `test_cfg03_param_audit::test_visible_dead_knobs_are_exactly_documented` (`flags.dig_pre_gate_enabled`), pre-existing |
| Стабильность B1/B4-набор (mca19 + qnd event/publication/metrics + `test_one_llm_call_one_send`) | **25 итераций, 0 падений** |
| `test_one_llm_call_one_send` изолированно | **25 итераций, 0 падений** |
| JS-unit (`node tests/js/*.js`, 113 файлов) | 8 падений — **ровно те же 8, что на базе** |

Подтверждённые pre-existing на `6674811f` (не «мои» и не чинились в этой
волне): `test_initiative_coordination` (4: conflict-defers, precheck-before-llm,
t1-nostalgia-refusal, t5-send-sites), `test_unified_image_request_round1026`/
`test_tool_coordinator_round1026` (дрейф allowlist путей),
`test_mca01_tx_task_supervisor_round1027::write_points` (дрейф счётчиков),
`test_prompt_field_audit`, `test_evol018_prompt_audit` (устаревшие пиннинги),
`test_speech_p0_a2_memory`, `test_summary_generator` (2),
`test_summary_two_call_round1022` (3), `test_verbilizer_response_modes_round1023`,
`test_cfg03_param_audit::dead_knobs`, webapp nav/glass/js-unit (8),
`test_youtube_multimodal_download_round1024` (20 errors),
`test_soul1_registry_completeness`.

## 7. Что осталось реальному развёртыванию

1. Первый боевой `source=quantum` от ANU (в тестах источник управляемый).
2. Живой суточный ритм: распределение интервалов и независимость двух чатов.
3. Продуктовое ощущение частоты при текущих `limits.qnd_*` (правится
   настройками, не кодом).
4. Визуальная проверка блоков «Статус»/«Аналитика» на реальных данных в
   браузере — в этой сессии Playwright/Browser Use к приложению не
   подключались, поэтому **честно не проверено**.
