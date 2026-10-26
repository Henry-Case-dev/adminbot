# P0 HOTFIX — независимый recheck R1/R2

- LANE_ID: **REVIEW-P0-RECHECK-R1R2**
- Проверенный кандидат кода: **d0123639** (R1 `9650e099` + R2 evidence), ветка `task/speech-p0-hotfix`, база `534ac7dd`.
- Режим: read-only. Прода/Telegram/LLM-вызовов и записи в БД не было; менялся только этот evidence-файл.
- **Вердикт: Needs Fixes.** R1 закрывает payload-блокер нормального L1-пути, но R2 остаётся частичным и не закрывает явное требование §5 источника; карта не привязана к R1/R2. Выпускать сейчас нельзя.

## 1. R1 — что проверено

`9650e099` меняет `_renders_extent_block`/`analysis_directive_needed` и передачу флага в `build_l2_plan_block`.

Проверено по коду и тестам:

- `_renders_extent_block` использует тот же `render_extent_block` и тот же `to_response_plan`, что и фактический сборщик; `resolve_mode_parts` (`services/prompt_style_blocks.py:416-442`) заменяет `MODE_*_BLOCK` непустым extent-блоком.
- `services/direct_chat_service.py:3769` передаёт результат предиката в `build_l2_plan_block`; `_l2_write_answer` строит extent-блок из того же `response_plan` (`:4758`) и отдаёт его composer (`:4798`).
- Тест `test_deep_research_extent_block_carries_analysis_texts_once`: deep/detailed/report → `ANALYSIS_DIRECTIVE_TEXT` 1, `ANALYSIS_WRITER_TEXT` 1, `MODE_DEEP_RESEARCH_BLOCK` отсутствует; `extent=auto` → 1+1 через режимный блок.
- Повторно прогнаны `tests/test_speech_p0_core_serious.py`, `test_speech_p0_hotfix_texts_analysis.py`, `test_speech_p0_a2_memory.py`: **31 passed**.

**Вывод:** для нормального пути `direct_l1_on` deep/report payload-блокер R1 закрыт. Это подтверждено unit/payload-тестом и инспекцией проводки, но не end-to-end тестом сервиса.

## 2. R2 — что доказано и что нет

Доказано:

- использованы реальные PG-тексты (Core `ead77b2ab509`, Expression, verbalizer `83ff62bbee40`) и реальное SQLite-окно A/B (59 сообщений);
- payload собран реальным `compose_prompt`, а не ручной склейкой; 4 raw-ответа LLM (old/new × A/B), HTTP 200;
- в payload new A/B `ANALYSIS_DIRECTIVE_TEXT`/`ANALYSIS_WRITER_TEXT` по 1, в old — 0;
- найден реальный self-echo (`graph_facts.id=21255`, `lore_stories.id=4` = production-ответ B 1660 симв.), то есть баг подтверждён в БД, а не только в теории.

Не доказано:

- **L1-маршрут не воспроизведён**: взята записанная трасса, а не реальный L1 old/new; `ANALYSIS-ROUTING-PRESERVED` остаётся неподтверждённым;
- **нет identity/persona, RAG/stats/lore, L2-summary**: system 6.2–8.2k против production 19–20k; это другая входная среда, поэтому production-эффект не подтверждён;
- **сравнение A не сопоставимо** (признано в самом evidence), B — только частично; по одному прогону на old/new при T=0.7;
- **9 проверок §5 не закрыты цитатами**: new A 742/4 абзаца против old 477/2 (стало длиннее), new B 2094/7 против old 1756/4 (стало длиннее и структурнее); first60 new B — всё ещё вступление «Ладно, брат, давай по-честному…», а не прямой вердикт. Утверждение «вердикт раньше» не подкреплено цитатой;
- **payload-артефакты содержат только sha12, без messages**; `metrics.json` нельзя независимо пересчитать из коммита, а harness зависит от непубличных scratch-файлов (`pg_dump.json`, `ctx_out.json`);
- **harness new-варианта передаёт `build_l2_plan_block(..., include_analysis=True)` принудительно**, поэтому он доказывает рендер блока, но не решение предиката в фактическом сервисе. Проводка проверена инспекцией, не end-to-end.

**Вывод:** R2 подтверждает наличие точных текстов в собранном payload, но не подтверждает production-поведение. Evidence сам называет R2 частичным — это честно, но §5 источника требует большего до deploy.

## 3. Находки

### F1. BLOCKER — §5 источника не выполнен, deploy-предусловие не наступило

Источник: `source-owner-p0-hotfix-chained-2026-10-25.md:256-277` — воспроизвести оба run, сравнить old/new на сопоставимых входах, проверить 9 пунктов, отдельно повторить self-echo, Reviewer обязан проверить raw output/payload/provenance/итоговые ответы; `:287` — «После успешной проверки выполнить штатный deployment».

Наблюдение: `probes_prod.md` §6 прямо фиксирует частичность; A не сопоставим; L1/identity/RAG/L2 отсутствуют; один прогон на конфигурацию; 9 пунктов не проверены с цитатами.

Влияние: выпуск сейчас обходит явное требование владельца и оставляет production-эффект неподтверждённым. Это не «canary после deploy»: проверка выполнима read-only до deploy, на тех же PG/SQLite.

Минимальная коррекция: один read-only полный прогон реального пайплайна (L1 + identity/persona + RAG/stats/lore + L2-summary), old/new, те же входы, по 2 повтора на кейс, с полным payload/raw/финальным ответом; проверить 9 пунктов §5 цитатами; повторить self-echo с исправленным кодом. Без сообщений в чаты.

### F2. BLOCKER (release gate) — карта не привязана к R1/R2

`requirements-map-p0-hotfix.json` (`ac9505aa`, ветка `task/speech-hotfix-map`): `candidate_commit=7eca3cbc`, **13 FAILED / 106 PENDING**, 160 строк / 101 уникальный `req_id`; `map_note` сам говорит, что R1/R2 не привязаны. В текущем worktree карта ещё старее: 79 PENDING, `candidate_commit` пуст.

`requirements_gate.py check --stage review --candidate d0123639` на таком состоянии не может пройти; release-gate обходить нельзя.

Минимальная коррекция PM: привязать candidate/evidence к d0123639 (или к финальному deploy-SHA), закрыть только реально доказанные R1-строки, оставить FAILED/PENDING честными, убрать duplicate `req_id`, выровнять 101↔100, прогнать review-gate. `READY_FOR_LIVE` ставить только для действительно postdeploy-only проверок с точным canary/rollback; R2-проба сюда не относится.

### F3. RELATED_SMALL — provenance payload не аудируется

`payload_*.json` содержат `messages_sha12`, но не messages; `harness_*` читает scratch-файлы вне репозитория. Маркеры 1× нельзя пересчитать из коммита.

Коррекция: добавить redacted-фрагмент payload/фикстуру с хэшами и счётчиками, либо тест, который собирает payload из checked-in фикстуры. Это требование `REVIEW-PAYLOAD-PROVENANCE`, а не новый эпик.

### F4. NONBLOCKING — остаточные риски R1

- `analysis_directive_needed` вызывается с `l1_plan`, тогда как writer использует `response_plan`; в текущей структуре `fallback_plan` и guard `direct_l1_on` делают расхождение практически недостижимым. Если kill-switch/legacy-путь входит в P0, безопаснее передать `response_plan or l1_plan`; отдельного блокера сейчас нет.
- `_synthesize_direct_answer` работает только при `not direct_l1_on` (`:3704`), то есть на legacy-пути; fallback-репак — деградированный путь. Для нормального P0 они не блокируют.
- `_renders_extent_block` при исключении возвращает False (fail-open к отсутствию текстов); фактический сборщик упал бы раньше на том же рендерере, поэтому это теоретический риск, не блокер.

## 4. Решение по deploy

**Не выпускать сейчас.** Postdeploy-наблюдение и rollback сами по себе не заменяют §5: проверка выполнима до deploy, без live-тестов в чатах. После полного read-only probe и обновления карты выпуск допустим по PET_PROJECT — сразу во все чаты, без канареек, с обязательным postdeploy-наблюдением.

Если после probe деплой состоится, postdeploy-проверки:

1. `/healthz` и отсутствие роста ошибок L1/L2; версия = deploy-SHA.
2. На первом реальном deep/serious запросе: в фактическом payload ровно 1× `ANALYSIS_DIRECTIVE_TEXT` и 1× `ANALYSIS_WRITER_TEXT`, `MODE_DEEP_RESEARCH_BLOCK` не дублируется.
3. Ответ A — короткий и прямой; B — подробный, но без навязанного психологического эссе, драматургии и выдуманных цитат.
4. Повторное обращение к тем же воспоминаниям не возвращает прежний ответ бота как факт; self-echo остаётся tentative.
5. Rollback на `534ac7dd`/2.58.130 при повторении исходного дефекта, росте ошибок или регрессии коротких ответов.

## 5. Что остаётся live после probe

- реальный production-эффект на 19–20k system и с RAG/identity — только после deploy, по реальным сообщениям владельца (не синтетическим);
- `ANALYSIS-ROUTING-PRESERVED` — только после реального L1-прогона old/new;
- повторный self-echo на живых воспоминаниях — после deploy, если не будет воспроизведён read-only.

## 6. Проверено / переиспользовано

Проверено сейчас: R1 diff и проводка `direct_chat_service.py:3769/4758/4798`, `prompt_style_blocks.resolve_mode_parts`, `tests/test_speech_p0_core_serious.py` (31 passed вместе с двумя соседними P0-файлами), R2 doc/metrics/payload/raw, карта `ac9505aa`. Переиспользовано: prior review `d4b3c979`, prior 44-тестовый прогон только как исторический контекст (не как доказательство для d0123639). Внешние источники не требовались — вопрос repo-local.
