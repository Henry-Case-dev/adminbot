# 2.58.215 — ограничения и честные границы (REVIEW)

Сборка подтверждает **код, тесты, инварианты и механику** трёх одобренных
слайсов. Всё, что требует production или живого внешнего вызова, здесь
**не выполнялось** и не имитируется.

## Не выполнялось в сборке (postdeploy)

1. **Реальный GLM-вызов L1** (`z-ai/glm-5.3-uncensored` через `nano-gpt.com`).
   Сквозной smoke резолвит маршрут и собирает снимок (`provider=nanogpt`,
   `endpoint=nano-gpt.com`, `key_slot=main`, 180/360, `max_tokens`,
   бюджет 4608), но **не делает HTTP**: capability-резолвер подменён на
   границе (`resolve_model_capability`), чтобы не ходить в сеть. Фактический
   вызов, `finish_reason`, расход и поля `L1_PLAN` в журнале — шаг D
   postdeploy-runbook.
2. **Vision live**: реальный `api.telegram.org` / локальный Bot API и
   re-drive 9 asset'ов — шаг E runbook. В сборке проверен реальный транспорт
   с инъекцией `cloud_fetcher` (локальный файл отсутствует → облачный
   fallback → байты), сеть не использовалась.
3. **Postdeploy-наблюдения**: gap-метрия живого loop, отсутствие
   `was missed by`, сверка `slot_claims ↔ summary_runs` (F3), эффективный
   env `MEDIA_DOWNLOAD_CLOUD_FALLBACK`, identity/health/schema — после деплоя.

## Известные ограничения кода (не блокеры деплоя)

4. **Scheduler crash-window**: claim-first резервирует слоты всех due-чатов до
   генерации. Падение процесса между `claim` и генерацией позднего чата
   оставляет `fired=1` без прогона; F3 отличает это от потери слота только по
   близости рестарта. Гарантии «ни один слот не потерян при жёстком kill» нет.
5. **Pre-existing vision grace 30 > interval 5**: у `vision_media_tick`
   фактический интервал `VISION_TICK_SECONDS = 5`, а `misfire_grace_time`
   30 s стоял до поезда и не менялся. Это существующая несогласованность, не
   регрессия кандидата; в scope SCH не входила (backlog).
6. **L1 N4 residual**: `L1_PLAN.provider`/`endpoint_host`/`key_slot` берутся из
   **primary** маршрута хода. При `failure_mode=provider_fallback` они называют
   первую ногу, а не ту, что фактически дала план; `fallback_chain` в событии
   не публикуется. Поле честное для основного пути, residual — для fallback.
7. **Scheduler F1 residual**: `_signal_release` при отсутствии записанного loop
   (`loop is None`) делает прямой `event.set()` — путь для тестов/ручной
   инъекции, не для двух реальных loop'ов. В production-пути сигнал идёт через
   `call_soon_threadsafe`. Backlog, не блокер.
8. **Local Bot API root cause** не устранён поездом: файлы могут продолжать не
   материализоваться; тогда работает облачный fallback (штатный путь после
   фикса). Это отдельный дефект, а не «Vision починен полностью».

## Проверочные границы

9. **JS 117/4**: те же 4 pre-existing падения (`asap6_wave2_ux_tabs_test.js`,
   `evol_cog_scene_test.js`, `round1025_ia_routing_test.js`,
   `ur_ui_settings_test.js`), что в 2.58.214; кодовые файлы поезда их не
   касаются.
10. **`tests/test_webapp_*.py` batch сознательно не запускался** (перезаписывает
    W10–W12 evidence). Запускался только `tests/test_webapp_js_unit.py` из
    mandatory-набора; после прогонов `git status --porcelain` пуст.
11. **Мутации не перезапускались**: код после одобрения не менялся, сборка
    только слила ветки. Артефакты: `evidence/l1/mutations.json` (8/8 killed),
    `evidence/vis/README.md` §4 (M1–M6), `evidence/sch/scheduler-p0-evidence-2026-11-18.md`
    §4 (M1–M7), SHA кандидатов — в `assembly.md`.
12. **Полный `tests/` (21 770 тестов)** не запускался — вне слайса; выборка
    соответствует «щадящему обязательному набору» задачи.
13. **Капабилити-резолвер в smoke подменён** — это осознанная граница «no
    network», а не замена тестируемого поведения: композиция маршрута
    (deadline/budget/key_slot/fields) исполняется реальным кодом `direct_l1`.

Ни один пункт не закрывает строки как VERIFIED; статус сборки — **REVIEW**,
деплой не выполнялся.
