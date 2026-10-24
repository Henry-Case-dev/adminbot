# Reviewer — P0 HOTFIX речи и анализа: независимый release-gate

- LANE_ID: **REVIEW-P0-SPEECH**
- Candidate: `7eca3cbccdf338a0f8180a6a1087ee262c805b5c` (код `51cee325` + evidence probes), ветка `task/speech-p0-hotfix`, база `534ac7dd`.
- Режим: read-only; код, карты, `current_task.md` и прод не менялись; Telegram/LLM-сообщения не отправлялись.
- **Вердикт: Needs Fixes.** Ниже два блокера по существу (R1 — фактический deep/report payload, R2 — сопоставимость и реальные сырые ответы) и один блокер учёта (R3 — карта требований). R1 и R2 нельзя закрыть evidence-комментарием: нужен минимальный код/проба и повторная проверка.

## Что подтверждено на candidate

| Проверка | Результат |
|---|---|
| 5 runtime-текстов §2 (BASE/HUMOR/LENGTH/FREQUENT/FACTUAL) | **байт-в-байт** совпадают с source; `PROFANITY_INSTRUCTIONS["frequent"]` — тот же текст |
| OFF/OCCASIONAL | не менялись; тесты фиксируют прежние тексты |
| Тексты §1 аддендума (`ANALYSIS_DIRECTIVE_TEXT`, `ANALYSIS_WRITER_TEXT`) | **байт-в-байт** совпадают с source |
| Core `ead77b2ab509` 3294 | `simplify_core_for_prompt` даёт ровно **1246 / 4e67334b00ad**, идемпотентно; P2/P5/P3 сняты, P1/P4/P6 остались; в Core нет analysis-блока; БД не перезаписывается |
| L2/lore | причинная драматургия, «эпичность», «усиление», импровизация убраны из активных канонов; JSON/evidence/имена/числа сохранены; PREV-слепки заморожены |
| current-turn / L2 / self-echo / provenance | current-turn исключён из истории; L2 keep-head + маркер «пересказ, не источник»; self-echo `tentative` и отфильтрован из фактического RAG; `read_policy_rank` подключён в direct-RAG |
| Границы | новых LLM-вызовов/слоёв/классификаторов/квот/обрезки ответа/жёсткой формулы не добавлено; fallback/retry не тронуты |
| Тесты | 4 профильных файла: **44 passed**; `py_compile` 15 изменённых services: **0**; plan-gate: `inventory=79 manual=81 errors=0`, **EXIT 0** |

Пробы действительно показывают полезное направление: c2 сокращён 1506→1020, c5 4934→2588, прямой ответ в c1/c2 — первое предложение, self-echo new отзывает выдуманный «февраль», c3/c4/c5 сохраняют живой мат и характер. Это ещё не доказательство production-поведения (см. R2).

## Блокирующие находки

### R1. BLOCKER — точные analysis-тексты не попадают в фактический deep/report payload

**Требование:** source §1 аддендума: точная target-инструкция и замена «сохрани структуру» должны быть в фактическом analysis-пути; карта: `ANALYSIS-EXACT-TARGET`, `ANALYSIS-WRITER-EXACT` (проверка «по сырому payload»). **Где:** `services/direct_chat_service.py:4757` строит `_plan_extent_block = render_extent_block(response_plan)` и передаёт его в композер (`:4797`, `:4824`); `services/prompt_style_blocks.py:436-437` при непустом extent-блоке **заменяет** `MODE_*_BLOCK`. `services/direct_l1.py:922-945` для `deep_research` возвращает `include_analysis=False`, поэтому plan-блок тоже не содержит текстов.

**Факт (локальная сборка на candidate, без LLM):**

| Вход | mode | extent-блок | `ANALYSIS_DIRECTIVE_TEXT` | `ANALYSIS_WRITER_TEXT` |
|---|---|---|---|---|
| c1-like (research, normal, answer) | casual | есть | **1** | **1** |
| c2-like (research, compact, answer) | casual | есть | **1** | **1** |
| c5-like (research, detailed, report) | deep_research | есть | **0** | **0** |

То есть для «разбери подробно» (и для любого analysis-запроса, который L1 отправит в `detailed/report` — ровно старый маршрут из `traces.md:32`) в фактическом payload остаётся прежний extent-блок «ПОДРОБНО. Раскрой тему полностью… Форма результата: отчёт», а новых owner-текстов нет. Это не косметика: если L1 не выполнит новое правило 7, дефект «эссе» вернётся, а код ему не помешает.

**Почему пробы это не поймали:** `evidence/p0-hotfix/probes/harness_build_payload.py:113-120` для `deep` подставляет `MODE_DEEP_RESEARCH_BLOCK` напрямую, минуя `render_extent_block`. Поэтому `probes.md:22-24` называет payload «фактическим», хотя c2/c5 собраны не тем путём, который исполняет `_l2_write_answer`. Тесты `tests/test_speech_p0_core_serious.py:137-150` и `tests/test_speech_p0_hotfix_texts_analysis.py:165-171` также вызывают `compose_verbalizer_system` **без** extent-блока; они зелёные, но проверяют мёртвую ветку.

**Минимальная правка:** обеспечить exact-тексты в реальном пути для research при непустом extent-блоке (например, добавлять `ANALYSIS_WRITER_TEXT` в plan-блок для research независимо от `deep_research`, либо включить его в extent-блок для research; дубль не допускать). **Минимальный recheck:** собрать system через `_l2_write_answer`/`compose_verbalizer_system` с `render_extent_block(ResponsePlan(task_kind='research', extent='detailed', structure='report'))` и показать ровно 1 вхождение каждого текста; тот же тест — для c2-like. Приложить новый payload, а не старый harness.

### R2. BLOCKER — пробы не воспроизводят production-контекст; главный кейс A не доказан

**Требование:** source §1/§4/§6: взять реальные production-трассы, сравнить старое и новое на сопоставимых входах, проверить сырой output; §6.8 — фактическое поведение улучшилось относительно предыдущей production-версии. **Факт:** `traces.md:9-10` — доставленный ответ A **2186 симв., 10–14 абзацев**, B **1658**; `traces.md:16` — production system **~19–20k**; `traces.md:19-20` — raw LLM output не персистится. Проба old c1 — **714/3**, new c1 — **655/3** (−8%); system пробы — **3.4–3.9k**, L2 синтетический, RAG/stats/L1 не воспроизведены (`probes.md:17-18, 99-104`). Следовательно:
- c1 old/new почти не различаются по длине и числу абзацев; уменьшение production-A с 2186 до 655 нельзя приписать исправлению — другой контекст;
- c2/c5 «old/new» собраны через `MODE_DEEP_RESEARCH_BLOCK`, которого в реальном deep-пути нет (R1), поэтому сравнение c5 4934→2588 не является сравнением production-путей;
- реальный сырой output двух показанных запросов не проверен; вместо него — новые генерации на synthetic L2. Это `UNVERIFIED`, а не «сырые ответы» из §1/§7.

**Минимальная правка:** либо восстановить сопоставимый контекст (L2/RAG/lore/доставленный текст из трассы) и прогнать old/new **тем же** сборщиком, что в бою, либо честно оставить это на postdeploy-наблюдение за органическими сообщениями (без тестовых сообщений в рабочих чатах) с точным rollback. **Минимальный recheck:** таблица c1/c2: длина, абзацы, позиция прямого ответа, число матерных корней, выдуманные даты/цитаты — на сопоставимом входе; для c1 — минимум два прогона, чтобы отделить эффект правки от temperature 0.7.

### R3. BLOCKER учёта — review-gate карты не проходит, acceptance ledger пуст

**Факт:** `requirements-map-p0-hotfix.json`: **79** items (не 100, как в брифе), **все 79 — PENDING**; `candidate_commit` пуст; `strict_evidence: true`, но `slice_graph_path: ""`; duplicate `req_id`: `MEMORY-NO-UNSUPPORTED-CAUSAL-STORY`, `MEMORY-SELF-ECHO-REPEAT`, `PROBES-TWO-RUNS`, `ANALYSIS-EXACT-TARGET`, `ANALYSIS-WRITER-EXACT`. `requirements_gate.py check --stage review --slice PROBES --candidate 7eca3cbc` → **EXIT 1**, 24 errors (candidate mismatch + mandatory PENDING). Пока статусы/evidence/candidate не приведены в порядок, нельзя выставить `VERIFIED` ни по одному требованию, даже если код проверен. Это работа PM/Orchestrator, не Reviewer; карту я не менял.

**Минимальное действие:** PM/Orchestrator обновляет статусы и evidence по фактам review, убирает duplicate IDs, заполняет `candidate_commit` и `slice_graph_path` (или осознанно снимает strict), затем повторно `--stage review`. Без этого release-gate формально красный.

## Неблокирующие наблюдения

- **c1, мат 3→0.** Для FREQUENT это допустимо: §5 прямо говорит, что отсутствие ругательства в конкретном ответе не означает потерю характера, а c2/c3/c4/c5 сохраняют мат (4 из 6 кейсов). Но это один прогон при temperature 0.7; частоту/«заметность» нельзя считать доказанной. Нужен второй прогон c1 или aggregate после deploy, не блокер.
- **`ANALYSIS_SYSTEM_PROMPT`.** В `services/mca_vision.py:1396` такая константа есть, но это OCR-промпт изображений, не чат-анализ. В chat-пути фиктивной константы не создано; формулировка evidence «констант нет вовсе» неточна, но на P0 не влияет.
- **`read_policy_rank`.** Код подключён, но на реальных данных не проверено, что обычные `confirmed`-факты не получают массово метку «(не подтверждено)» из-за отсутствия v17-атрибуции. Нужен один реальный RAG-payload после deploy; сейчас это риск, не блокер.
- **`ANALYSIS-ROUTING-PRESERVED`.** Правило 7 меняет extent/structure для персонального анализа; L1 old/new не воспроизведён, поэтому «маршрутизация сохранена» не доказана. Это часть R2.

## Acceptance ledger (сводка)

- **VERIFIED:** 5 текстов §2; OFF/OCCASIONAL; Core-фильтр 3294→1246; L2 keep-head/маркер; current-turn; self-echo tentative/фильтр; L2/lore фактология; 44 теста; py_compile; plan-gate.
- **FAILED:** exact analysis-тексты в фактическом deep/report payload (R1).
- **UNVERIFIED:** реальные сырые ответы production и сопоставимость old/new (R2); `ANALYSIS-ROUTING-PRESERVED`; review-gate/ledger (R3).
- **N/A_WITH_REASON:** `ANALYSIS_SYSTEM_PROMPT`/`ANALYSIS_USER_TEMPLATE` в chat-пути — таких констант там нет; vision-константа к задаче не относится.
- **READY_FOR_LIVE:** не выставлен: сначала R1/R2/R3.

## Что проверено / что переиспользовано

Проверено лично: diff `534ac7dd..51cee325` по 15 services; byte-compare 5+2 текстов; Core-фильтр на snapshot; сборка c1/c2/c5-like через `render_extent_block`; 44 теста; py_compile; plan-gate/review-gate; raw c1–c6 old/new + self-echo; карта и duplicate IDs. Переиспользовано: `audit.md`, `traces.md`, `active-core.md`, `memory-provenance.md`, `probes.md` — с проверкой их утверждений по коду/файлам, без доверия на слово. Внешние источники не требовались: спорных внешних API/версий нет. Прод, SSH, Telegram и LLM-провайдер не использовались; `.env` в worktree отсутствует, поэтому дополнительный L1-прогон не выполнен.

## Следующее действие

Builder: закрыть R1 минимальной правкой в реальном пути и добавить тест на фактический extent-блок; затем пересобрать c2/c5 payload и c1 на сопоставимом контексте (R2). PM/Orchestrator: привести карту/ledger в порядок (R3) и повторить `--stage review`. После этого — узкий recheck R1/R2 и только затем решение о deploy. Деплой не объявляю.