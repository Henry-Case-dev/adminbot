# audit-prompt-matrix.md — SOUL-1 / AUDIT-1: инвентаризация всех речевых путей и источников промпта

- **Lane:** AUDIT-1 (read-only). **Baseline:** master HEAD `a854ad95`. **Дата:** 16.10.2026.
- **Источник истины:** `plans/features/soul-1/source-current-task.md`
  (sha256 `8C42DDFABCE635FE4E1F24F9522FF8642F3BD3049FAC05C77CA162687051196B`), покрытие SOUL-01 (§2) + факт-база для SOUL-03 (§4/§5) и SOUL-05 (§6).
- **Evidence:** `plans/features/soul-1/evidence/direct-runtime-assembly.txt` (РЕАЛЬНЫЙ дамп сборки, offline),
  `plans/features/soul-1/evidence/prompt-matrix.json` (22 строки-пути).
- **Метод:** чтение текущего кода + исполнение production-сборщиков промпта офлайн (Telegram/LLM/БД не вызывались).
- **Локальный PG DOWN** (`WinError 1225`) → `hot_config.get()` вернул код-канон, persona/lessons/scoped-style = пусто.
  Это значит: дамп показывает **структуру и порядок блоков** (это и есть предмет аудита), а не прод-значения.

## 0. Что доказать НЕ удалось (честная граница)

1. **Эффективные прод-значения `prompts.*`** — недостижимы в этой линии (прод-SSH/прод-PG вне scope). Единственное проверенное
   прод-свидетельство: 6 summary-ключей genuinely-custom на baseline 2.58.33
   (`plans/archive/mca-asap21-summary-quality-ui-cleanup-round1028/prompt-map-audit.md` §2). Для direct/factcheck/search/checkup/
   youtube/webpage/memory статус custom **не проверен**.
2. **Per-chat prompt-значения**, кроме `prompts.summary_cover_style` — не проверены.
3. **DB-слои** (persona, character layers, lessons, scoped style) локально пусты; их вклад в текст не воспроизведён.
4. **Сквозные записи** Initiative/Summary/lore/dreams не прогонялись (нужны БД + worker-цикл).
5. Дамп — не proof прод-поведения: это proof **кода сборки** (какие блоки, в каком порядке, откуда).

## 1. Реестр prompt-ключей (24 шт., `services/param_catalog.py:546-661`)

Свойство `per_chat=True` в каталоге — выводимое (категория prompts ∧ не secret), **не факт чтения**.
Фактически per-chat читается только `prompts.direct_chat_system_prompt` (Direct legacy) и `prompts.summary_cover_style`.

Grep-перепись читателей даёт **25** литералов `prompts.*` в рантайме, а в каталоге — **24**:
`prompts.direct_l1_planner_system_prompt` (L1 planner) читается через `resolve_prompt`, но **UI/каталог-ключа не имеет** (`_PROMPTS` его не содержит) →
его нельзя ни отредактировать из админки, ни увидеть в списке, ни мигрировать.

| Группа | Ключи | Читатель |
|---|---|---|
| direct_chat | `direct_chat_system_prompt`, `direct_chat_synthesizer_system_prompt`, `direct_chat_verbalizer_system_prompt`, `direct_l1_planner_system_prompt` (есть в коде/`resolve_prompt`, но **нет** в `_PROMPTS`) | `direct_chat_service.py:2344, 3640, 3943, 4095, 4116, 7551` |
| verbilizer | `verbilizer_mode_casual/serious/deep_research`, `verbilizer_default_mode` | `prompt_style_blocks.py:216,222` |
| factcheck | `factcheck_system_prompt`, `factcheck_analyst_system_prompt`, `factcheck_verbalizer_system_prompt` | `factcheck_service.py:181, 223, 251` |
| summary | `summary_system_prompt`, `summary_editor_system_prompt`, `summary_narrator_system_prompt`, `summary_l1_clusterizer_system_prompt`, `summary_l2_writer_system_prompt`, `summary_cover_style`, `summary_cover_style_id` | `summary_generator.py:987,3765,3805`; `summary_l1_clusterizer.py:1525,1746`; `summary_l2_writer.py:1661`; `summary_execution_input.py:114` |
| прочие | `search_system_prompt`, `checkup_system_prompt`, `youtube_system_prompt`, `youtube_video_system_prompt`, `webpage_system_prompt`, `extract_system_prompt`, `compress_system_prompt` | `search_service.py:92`; `checkup_service.py:47`; `youtube_summarizer_service.py:112,147`; `web_summarizer_service.py:73`; `summary_memory.py` |

**Вне каталога (не PG-редактируемо, ключа `prompts.*` нет):** `dream_prompts.py:42,154,301`, `lore_prompts.py`,
`nostalgia_prompts.py`, `dossier_prompts.py:21,63,92`, `smartmodule_phrases.py`, `direct_execution.py:641 ORCHESTRATOR_SYSTEM_PROMPT`,
`anticliche_worker.py:150`, `negative_constraints.py:813`, `mca_episodes.py`, `mca_vision.py:906`, `self_reflection.py:108`,
`memory_maintenance.py:747`, `initiative_observer.py:895`, `video_cascade_client.py:173`.
→ Любая инъекция «ядра», работающая только с каталогом, **не видит** эти пути.

## 2. Матрица путей (полные поля — в `evidence/prompt-matrix.json`)

| path_id | Триггер | Слой решения | Writer (file:line) | Publisher | Ключи | Канал |
|---|---|---|---|---|---|---|
| DIRECT-L1 | адресованное сообщение | L1 planner LLM | `_plan_direct_l1` `direct_chat_service.py:3571` | — | `direct_l1_planner_system_prompt` | internal |
| DIRECT-L2 | после L1 + тулов | ResponsePlan / `L1Plan.to_response_plan` | `_l2_write_answer` `:3918` | `_send_direct_answer` `:4219` → `telegram_send` | `direct_chat_verbalizer_system_prompt`+`verbilizer_mode_*` | plain / safe-HTML |
| DIRECT-SYSTEM2 | tool-loop, System2 ON и `not direct_l1_on` | Stage-1 `response_mode` | `_synthesize_direct_answer` `:4025` | `_send_direct_answer` | `direct_chat_synthesizer_*`,`direct_chat_verbalizer_*` | plain / rich |
| DIRECT-LEGACY-SYSTEM | tool-loop системный промпт | — | `_handle_turn` `:2344` + `:4370` | `_send_direct_answer` | `direct_chat_system_prompt` (**единственный с per-chat слотом**) | plain / rich |
| INITIATIVE-L1 | due-намерение | L1 (REPLY/REACT/SILENT) | `plan_initiative_decision` `:7518` | — | `direct_l1_planner_system_prompt` | internal |
| INITIATIVE-WRITER | L1=REPLY | L1Plan | `generate_initiative_reply` `:7571`→`_l2_write_answer` | `telegram_send.send_text` + `bot_output_ledger` | `direct_chat_verbalizer_*` | plain |
| FACTCHECK-TWO-CALL | `/factcheck` | analyst JSON | `_check_claim_two_call` `factcheck_service.py:216` | caller → `telegram_send` | `factcheck_analyst_*`,`factcheck_verbalizer_*` | plain |
| FACTCHECK-SINGLE | legacy | — | `_check_claim_pipeline` `:160` | caller | `factcheck_system_prompt` | plain |
| SEARCH | `/search` | — | `search_service.research:57` | `smartmodule_utils.send_text` | `search_system_prompt` | plain |
| WEBPAGE | URL | — | `web_summarizer_service.summarize:39` | `smartmodule_utils.send_text` | `webpage_system_prompt` | plain |
| YOUTUBE | YouTube-ссылка | cascade | `youtube_summarizer_service:64,80` | `smartmodule_utils.send_text` | `youtube_*_system_prompt` | plain |
| CHECKUP | расписание | — | `checkup_service.checkup:43` | `smartmodule_utils.send_text` | `checkup_system_prompt` | plain |
| SUMMARY-LEGACY-SINGLE | OFF/LEVEL-3 | — | `summary_generator:987` | `summary_generator._deliver_*`→`send_text` | `summary_system_prompt` | plain/rich |
| SUMMARY-LEGACY-TWO-CALL | legacy | editor | `summary_generator:3765` | то же | `summary_editor_*`,`summary_narrator_*` | plain/rich |
| SUMMARY-HYBRID | расписание (primary) | L1 кластеризатор → L2 писатель | `summary_l1_clusterizer.py:1668`; `summary_l2_writer.py` | то же | `summary_l1_clusterizer_*`,`summary_l2_writer_*`,`summary_cover_style*` | rich+обложка |
| DREAMS-LORE | ночь | distill→bridge→evolution | `dream_worker:1327,2297,2778` | — | **нет ключа** | internal |
| LORE-DOSSIER | tick | classify→A/B→synthesize | `lore_worker:712,798,834,882,1323,1484,1540` | safe-HTML путь Direct | **нет ключа** | internal/rich |
| NOSTALGIA | cron | candidate+budget | `nostalgia_worker._llm_once:744` | `_delegate_initiative:604`→`telegram_send` | **нет ключа** | plain |
| DOSSIER-EPISODES-VISION | фоновые | — | `mca_episodes.py:*,mca_vision.py:906` | internal | **нет ключа** | internal |
| MEMORY-EXTRACT-COMPRESS | worker | — | `summary_memory.py:*` | — | `extract_*`,`compress_*` | internal |
| TEMPLATE-PHRASES | команды/ошибки | детерминированно | `smartmodule_phrases.py:11-181` | `handlers/direct_chat.py:253`,`smartmodule_utils.send_text` | **нет ключа** | plain |
| MANUAL-TEST | UI/скрипты | копии writer'ов | `summary_test_run.py` (не вызывает `telegram_send.*`) | — | ключи тестируемой стадии | UI |

## 3. Реальная сборка (offline-дамп, `evidence/direct-runtime-assembly.txt`)

**P1 Direct L2 (primary), система = 4 блока, `decomposition_exact=True`:**

| # | Блок | chars | tok | Источник |
|---|---|---|---|---|
| 0 | base канон | 1690 | 581 | `resolve_prompt('prompts.direct_chat_verbalizer_system_prompt')`→код |
| 1 | `ОЖИДАЕМАЯ ПОЛНОТА` (extent=detailed) | 211 | 70 | `response_extent.render_extent_block` — **заменяет** MODE_serious |
| 2 | `<Persona>`+`<Character_Rules>` (character_block) | 125 | 40 | `bot_persona` (БД); хвост того же system-сообщения |
| 3 | `<Style_Requests>` | 56 | 18 | `mca_style_scope` scoped-просьбы |

Σ system = 2088 chars / 709 tok. user = 277 chars, порядок **time_line → plan_block → speech_block → lessons_block → user_blocks[] → `<Tool_Evidence>`**
(`direct_chat_service.py:3963-3981`, `decomposition_exact=True`). MODE-блок на этом пути не используется.

**P4 Direct L1:** system = 2423 chars — чистая база (`prompts.direct_l1_planner_system_prompt`, `True` по сравнению),
**без** STYLE/SUFFIX/TYPOGRAPHY/MODE; user = `build_l1_context`, секции: СООБЩЕНИЕ / ПОСЛЕДНИЕ СООБЩЕНИЯ / УЧАСТНИКИ /
РЕЧЕВОЙ СИГНАЛ / ДОСТУПНЫЕ ВОЗМОЖНОСТИ / ХАРАКТЕР (кадр). Характер — **только голова 400 символов** (`L1_PERSONA_FRAME_CHARS`).

**P5a System2 Stage-1:** 1107 chars, единственный блок — база синтезатора; **ни персоны, ни стиля, ни полноты**.

**P3 kill-switch `SMART_VERBALIZER_MODES_ENABLED=OFF`:** подставляется `PREV_CHAT_VERBALIZER_R1023` (1324 chars) →
после scrub 1289 chars (`removed=1`). Т.е. легаси-cap-текст **всё равно** вычищается на L2 (см. §5).

**P4b:** `L1Plan(extent='one_word').to_response_plan()` → `'micro'`; в `response_extent.EXTENTS` нет `one_word`.

## 4. Дубли и конфликты канонов (источник «токсичного бота»)

1. **Нет единого общего ядра.** Шесть независимых сборщиков system-сообщения: `prompt_style_blocks.compose_verbalizer_system`,
   хвост в `direct_chat_service._handle_turn`, `summary_generator`, `factcheck_service`, `search/web/youtube`, `checkup_service`.
   Общий — только `STYLE_BLOCKS_SUFFIX` (ANTI_BOT + ASYMMETRY) и он подключён **не ко всем** канонам.
2. **≥14 независимых копий «токсичной/циничной/саркастичной» персоны:** `chat_prompts.py:74,88,108,131,162,203,238,315`,
   `checkup_prompts.py:22,36,42,56`, `factcheck_prompts.py:39,68,97,223`, `search_prompts.py:24,36,50,62`,
   `summary_prompts.py:40,76,229,238,257,546,629,810,852,882`, `web_prompts.py:23,44`, `youtube_prompts.py:25,46,88,109`,
   `lore_prompts.py:64,89,107`, `nostalgia_prompts.py:24,32`, `dossier_prompts.py:26`, `dream_prompts.py:297`,
   `smartmodule_phrases.py:161` (`CHAT_PERSONA_PHRASE`, рендер `handlers/direct_chat.py:253`), `prompt_style_blocks.py:48,123,130`.
   Каждая копия = **отдельный** PG-ключ (или вообще без ключа) и отдельный writer.
3. **Обязательная краткость vs развёрнутость.** Старый cap живёт в PREV-слепках (`PREV_CHAT_VERBALIZER_R1023`) и в PG-кастомах;
   актуальный контракт — extent-блок. Скрейв конфликта есть, но включается **только** для семейства
   `{detailed, longform, exhaustive}` (`response_extent.py:40,494-498`).
4. **Одна метафора (ASYMMETRY п.3) vs длинный текст** — конфликт инструкций внутри одного собранного промпта: ASYMMETRY требует
   «одну контекстную метафору», extent=longform требует законченного полного результата.
5. **Двойной рендер владельческой личности в одном ходу:** персона+правила+style+lessons+speech идут в системный промпт tool-loop
   (`direct_chat_service.py:2371-2430`, затем `:2669` extent) **и** те же `character_block`/`style_directives` уходят в
   verbalizer/System2 (`:3212-3228`). Core, добавленный только в одно место, даёт противоречие в одном запросе.
6. **Персона из БД vs `personas.system_prompt_overrides`**: `bot_persona.build_persona_prompt_block` рендерит `overrides` как
   строку «Характер: …» внутри `<Persona>` (`bot_persona.py:304-305`), при `frame is not None` — из `BehaviorFrame`
   (`:271-282`). Т.е. реальное поведение задаётся данными, а не каноном каталога.
7. **dreams `PERSONA_EVOLUTION_PROMPT`** (`dream_prompts.py:301`) умеет переписывать ту же персону, которую рендерит
   Direct/Initiative → прямой conflict-surface с новым Personality Core.

## 5. Тихие фолбэки (рендерят старого «токсичного бота» без сигнала)

| # | Триггер | Фолбэк | Код |
|---|---|---|---|
| 1 | `SMART_VERBALIZER_MODES_ENABLED=OFF` | `PREV_CHAT_VERBALIZER_R1023` (cap-текст) вместо всего тела вербализатора | `direct_chat_service.py:3942-3945` |
| 2 | пустое/whitespace значение в PG | молча возвращается код-канон, **без** WARN/счётчика | `prompt_style_blocks.py:186-197` |
| 3 | PG недоступен | `hot_config.get` отдаёт дефолт → весь per-chat слой молча игнорируется | `hot_config.get` |
| 4 | `character_layers_enabled()=OFF` | персона деградирует к `resolve_bot_persona`+`get_traits` (иной текст) | `direct_chat_service.py:2367-2370` |
| 5 | persona-гейт OFF / persona пуста | `character_block=''` → вербализатор теряет личность, сигнала нет | `:2360-2384` |
| 6 | `plan_response_mode(ResponsePlan)` | `'serious'` для любого не-rich/report плана (включая micro-болтовню) | `direct_l1.py:186-188` |
| 7 | extent `one_word` | схлопывается в `micro` — контракт «одно слово» недостижим | `direct_l1.py:146-147` |
| 8 | `scrub_for_plan` в `_l2_write_answer` | **не** за гейтом `modes_on` (в отличие от System2 `:4135`) | `direct_chat_service.py:3955-3958` |
| 9 | пустой/упавший L2 | `fallback_text=None` → `None` (честный отказ); System2 отдаёт черновик | `:4012`, `:4169` |
| 10 | любой не-direct путь | собственная копия токсичной персоны | см. §4.2 |

## 6. Персистентные custom PG-промпты, которых не касается миграция дефолтов

Контракт: `services/prompt_migrations.py` переписывает PG-значение **только** если оно байт-в-байт равно известному
`PREV_*`-слепку; genuinely-custom остаётся (лог `[prompt_migration] кастом юзера — НЕ трогаем`).

Доказано на baseline 2.58.33 (28.09.2026), только summary-ключи:

| Ключ | sha256-12 | len | Класс |
|---|---|---|---|
| `prompts.summary_l1_clusterizer_system_prompt` | `8237880de15f` | 3778 | custom |
| `prompts.summary_l2_writer_system_prompt` | `c913a4b4c53d` | 3110 | custom (реально пишет prod-статью) |
| `prompts.summary_system_prompt` | `67344524cd16` | 3578 | custom |
| `prompts.summary_editor_system_prompt` | `14ae80070e29` | 2063 | custom |
| `prompts.summary_narrator_system_prompt` | `58c9d4237eaa` | 1693 | custom |
| `prompts.summary_cover_style` | `faed624c9d0b` / per-chat `35013bd88081` | 33 / 110 | custom; **единственный** реально per-chat prompt |

Для direct/factcheck/search/checkup/youtube/webpage/memory статус custom **не проверен** (§0.1).
Следствие: Core-инъекция через правку код-канона или миграцию дефолтов **не изменит** прод для этих 6 ключей.

## 7. Контракты приоритетов (для SOUL-03/04/05)

| ID | Цепочка | Код |
|---|---|---|
| PC1 | chat override → global → код-канон (только `direct_chat_system_prompt`) | `direct_chat_service.py:2343-2347` |
| PC2 | L1/L2/System2 stage-ключи: **global → канон** (per-chat не читается) | `:3640-3642,3942-3945,4095-4097,4115-4118` |
| PC3 | `base(+SUFFIX+TYPOGRAPHY)` → `[extent XOR MODE_*]` → `[FORMAT только deep_research]` → `character_block` → `style_directives` | `prompt_style_blocks.py:309-324` |
| PC4 | легаси system: `system_prompt` → `<Persona>` → `<Character_Rules>` → `<Style_Requests>` → `<Verified_Lessons>` → `<Speech_Understanding>` → extent | `direct_chat_service.py:2371-2430, 2669` |
| PC5 | L2 user: `time_line → plan_block → speech_block → lessons_block → user_blocks[] → <Tool_Evidence>` | `:3963-3981` |
| PC6 | слои характера `owner_core→owner_style→…`; `system_model`/frame при `self_model_enabled()` | `bot_persona.py:43,45,271-314` |
| PC7 | scoped style: **participant > topic > chat**, только форма | `mca_style_scope.py`, `:2390-2391` |
| PC8 | self-model: `SettingState → resolve_is_aware_ai → guards → select_behavior → render_frame_block` | `mca_self_model.py` |
| PC9 | scrub только для `{detailed,longform,exhaustive}`; на L2 — вне гейта `modes_on` | `response_extent.py:494-498`, `:3955-3958` |

## 8. Что мешает «наивной» инъекции одного Core

1. Нет единой точки сборки system-сообщения (6 независимых семейств, §4.1).
2. ≥14 независимых копий токсичной персоны; общий только `STYLE_BLOCKS_SUFFIX`, и не везде (§4.2).
3. Промпты **вне** каталога (dreams/lore/nostalgia/dossier/phrases/orchestrator) не PG-редактируемы и невидимы для правки каталога.
4. Персистентные custom PG-значения перекрывают код-канон (§6).
5. Персона рендерится дважды в одном ходу на primary Direct (§4.5).
6. `prompts.direct_chat_system_prompt` не читается ни в L1, ни в Initiative → Core там не появится.
7. Четыре рубильника (`SMART_VERBALIZER_MODES_ENABLED`, `flags.persona_enabled`, `character_layers`, `response_plan_enabled`)
   молча меняют весь стилевой слой.
8. Фолбэки не эмитят счётчик/WARN → «ядро активно» сегодня недоказуемо телеметрией.

## 9. Вывод по SOUL-01.5

Пути **без общего ядра**: L1 planner, Direct L2, Direct legacy-system, System2 Stage-1, Initiative, Factcheck (оба),
Search, Webpage, YouTube (оба), Checkup, Summary (legacy×2 + Hybrid), Dreams, Lore/dossier, Nostalgia, Episodes/vision,
Memory extract/compress, Template-phrases. Общее между ними — только `resolve_prompt`-паттерн «PG→код» и (частично) `STYLE_BLOCKS_SUFFIX`.
**Единого prompt-core в master нет.** Вердикт SOUL-01.5: инвентаризация выполнена, дамп реален, но «одно ядро» потребует
явного дизайна точки инъекции (SOUL-02) и решения по §8.1–§8.8.

## 10. Артефакты

- `plans/features/soul-1/audit-prompt-matrix.md` (этот файл, ≤300 строк)
- `plans/features/soul-1/evidence/prompt-matrix.json` (22 пути, evidence-класс)
- `plans/features/soul-1/evidence/direct-runtime-assembly.txt` (реальная сборка, 6 сценариев)
- Скрипты проб: `OPENCODE_WORKFLOW_SCRATCH/soul1_dump_assembly.py`, `soul1_probe_pg.py`
