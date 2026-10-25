# Reviewer — P0 SPEECH: Core / L1 / no-meta / harness (slice)

- **LANE:** `REVIEW-SPEECH-CORE-L1-META` (read-only, один lens; субагенты не запускались).
- **Candidate:** `c0d5a3d3fc65f15a81f337bd322d1dd9ff2c226d` (`task/speech-p0-hotfix`), worktree `C:\Code\Python\adminbot-wt-speech-rev`, clean, detached.
- **Base:** `534ac7dd` (production 2.58.130).
- **Source:** `source-owner-p0-corrective-2026-10-25.md` §1.1, §1.2, §1.4 (частично), §3.
- **Alias slice:** `f42e2257` уже принят отдельно; здесь не пересматривался, регрессий в его файлах не найдено.
- **Вердикт: `Needs Fixes`.**

## 1. Acceptance ledger

| Требование | Статус | Доказательство |
|---|---|---|
| CORE: активный owner-Core 3294/`ead77b2ab509` доходит до payload целиком, без бюджетного обрезания | **VERIFIED** | независимая сборка `compose_prompt` с `CoreRef(text=active-core)`: слой `core` = 3294, `sha12=ead77b2ab509`, в system ровно 1 копия; live 0428c271: срез system 3294/`ead77b2ab509` (raw_new_code_A), `prompt_composer.simplify_core_for_prompt` — identity |
| CORE: новых квот на инструкции не введено | **VERIFIED** | фильтр снят, литералы `_CORE_*` — исторические; новых лимитов/обрезок в diff нет |
| L1: просьба разобрать свои сообщения/историю → `research` | **VERIFIED для A/B** | канон 9288/`23aae0c9499d`, правило 7 семантическое; live natural A/B = research 2/2, mode serious, 1 попытка; forced 2/2. Детерминизм на всей истории **не доказан** (2 natural-плана) |
| L1: глубина не диктует длину | **VERIFIED** | правило 8 + `ANALYSIS_*` без приказов объёма; live ответы 320–882 симв., `max_tokens` не достигнут, обрезания нет |
| L1: нет хардкода фраз запроса | **VERIFIED** | в коде нет фразовых матчеров; в каноне нет «проанализируй мои сообщения», «мои сообщения», «в чате», «злобный»; само решение — LLM |
| L1: natural и forced-research — разные реальные сценарии | **VERIFIED** | natural `plan_source=llm`; forced `plan_source=forced`, `confidence=1.0`, честно помечен |
| SPEECH: нет мета-вступлений | **FAILED/UNVERIFIED на кандидате** | на 0428c271 — 5/8 с преамбулами; на c0d5a3d3 live-прогона нет, `meta-fix.md` отсутствует; авто-детектор слеп к A1 |
| SPEECH: нет навязанной структуры | **VERIFIED на 0428c271 / NOT OBSERVED на c0d5a3d3** | 0 нумерованных строк, 0 «во-первых»; один `**Вердикт:**`; новая директива в live не проверена |
| SPEECH: краткость естественная, не обрезание | **VERIFIED** | постпроцесса/тримминга нет; ответы 320–882; `NO_META` не задаёт длину/схему |
| FREQUENT: настоящий режим из реального конфига, без обязательных few-shot | **VERIFIED** | PG global/chat `profanity=frequent`, rev 2; `expression` 1069, `PROFANITY_FREQUENT_TEXT`; `expression_examples` absent, режим работает |
| HARNESS: тот же commit, что и код | **FAILED** | исполненный harness `9420ce0c…` + код 0428c271; у кандидата harness `e5a29e79…` + код c0d5a3d3 |
| HARNESS: честные счётчики | **PARTIAL** | `ANALYSIS_*` считаются точными текстами; `core.chars` = длина revision (`0`), `core_marker` всегда false |
| HARNESS: реальный RAG/Memory, без неэквивалентных результатов | **PARTIAL/FAIL** | RAG-блок есть (2027, 39 строк), но выборка — дамп 40 facts, не `get_rag_facts(query)`; блок одинаков для A/B (`1fdb8b237233`) |
| §1.4: оба проблемных запроса и короткие повседневные сообщения | **FAILED** | A/B проверены; case C / короткого бытового сообщения нет (`--case` choices A/B) |
| Регрессии: существующие контракты | **FAILED (1 новый)** | `test_p4_l1_planner_system_matches_recorded_dump` красный: фикстура 8574/`8ef75b632d12`, активный канон 9288/`23aae0c9499d`; на базе 4 падения, на кандидате 5 |
| Fallback/retry сохранены | **VERIFIED (с оговоркой)** | логика не менялась; fallback-репак может выбросить plan-блок (существующее поведение) |
| Instruction quotas | **VERIFIED: не введены** | Core-фильтр снят; `NO_META` — инструкция, не лимит |

## 2. Девять §5-проверок (источник — raw 0428c271; c0d5a3d3 меняет только no-meta)

| # | Проверка | Статус | Комментарий |
|---|---|---|---|
| 1 | Прямой ответ без обязательного мета-вступления | **FAIL на 0428c271; NOT OBSERVED на c0d5a3d3** | 5/8: «Ладно, глянул…», «Да без проблем, сейчас разложу», «Давай посмотрим», «Давай разберём», «Давай разберёмся» |
| 2 | Нет навязанной структуры эссе | **PASS на 0428c271; NOT OBSERVED на c0d5a3d3** | 0 пунктов/«во-первых»; один `**Вердикт:**` |
| 3 | Нет искусственной драматургии | **PASS (reused)** | 0 вхождений «сцена/драма/кульминация» |
| 4 | Нет неподтверждённых дат/цитат | **PASS с оговоркой (reused)** | 0 годов/месяцев; `in_ctx=false` — гипотетические характеристики в кавычках, помечены «в смысле/с позиции» |
| 5 | L2 не выдаёт интерпретацию за историю/self-echo | **PASS (reused)** | 0 `[Бот]`, RAG-маркеры 18 «(не подтверждено)» + 4 «(предположение)» |
| 6 | FREQUENT — естественный мат | **PASS** | frequent из PG, few-shot отсутствуют |
| 7 | Явный разбор — подробно | **PASS** | research, 320–882, без обрезания |
| 8 | Обычный вопрос — коротко | **NOT OBSERVED** | нет case C / короткого бытового сообщения |
| 9 | Core и индивидуальность сохранены | **PASS** | core 3294/`ead77b2ab509`, identity 5048 |

Проверки 1–2 относятся к изменённому в c0d5a3d3 контракту; переносить их PASS с 0428c271 на кандидат нельзя. Проверки 3–7, 9 — код тех же путей, не изменённых c0d5a3d3, поэтому использованы как reused evidence с явной привязкой к 0428c271.

## 3. Выполненные прогоны

**Обязательный набор 1:**
```
py -3 -m pytest tests/test_speech_p0_core_serious.py tests/test_speech_p0_corrective_l1_route.py tests/test_p0_prompts_core.py tests/test_prompt_migrations.py tests/test_soul1_composer_parity_off.py -q
=> 5 failed, 83 passed, 2 warnings in 4.49s
```

**Обязательный набор 2:**
```
py -3 -m pytest tests -k "speech_p0 or direct_l1 or prompt or composer" -q
=> 5 failed, 798 passed, 14950 deselected, 5 warnings in 48.31s
```

**Harness self-check (кандидат, clean):**
```
py -3 probes_full/harness_probe_full.py --self-check
=> self_check: PASS
   counts_1x1/ascii_marker_zero/payload_1x1/predicate_*/mode_research_serious/modules_under_root = true
   code_l1_canon_material_routing/code_l1_canon_not_pg_stage/core_full_not_truncated = true
   no_meta_research_plan_once/no_meta_casual_plan_once/no_meta_deep_auto_mode_once/meta_phrases_absent_from_prompts = true
   git.commit = c0d5a3d3fc65f15a81f337bd322d1dd9ff2c226d, dirty=false
   code_l1_canon = 9288 / 23aae0c9499d
```
Хеш harness кандидата: `e5a29e796928d273fa52d0ef2f3296d27e83ba2f9a7cf2e7bfae8c1cc73f0732` (42316 байт). Исполненный в probes_final2: `9420ce0cbad2956675a935cd18af4b02a55730e2ac1b3ab38f28dd49192064ae` (39512 байт, 0428c271/be24e28f).

**Core payload (независимая сборка композера):**
```
core chars 3294 sha12 ead77b2ab509
core layer chars [3294] rendered [True]
exact core in system: True count: 1
system chars 4249
versions.core repr: '8'
```
Дополнительно по live raw 0428c271: срез system после `channel_canon` = 3294, `sha12=ead77b2ab509`, ровно 1 вхождение.

**No-meta single-copy (c0d5a3d3, modes_on / modes_off):**
```
research/compact/answer   serious      plan=1 sys=0
research/detailed/report  deep_research plan=1 sys=0
research/auto/report      deep_research plan=0 sys=1 (modes_off: plan=1 sys=0)
casual/compact/chat       casual       plan=1 sys=0
answer/normal/answer      casual       plan=1 sys=0
```

**База vs кандидат (паритетный файл):**
```
534ac7dd: 4 failed, 9 passed  (test_p4_l1_planner_system_matches_recorded_dump PASS)
c0d5a3d3: 5 failed, 8 passed  (test_p4... FAIL: 23aae0c9499d != 8ef75b632d12)
```
То есть 4 падения — предсуществующие, **пятое — регрессия кандидата**, а не «все 5 предсуществующие».

**Review-gate:**
```
py -3 <OPENCODE_CONFIG>/tools/requirements_gate.py check --map plans/features/asap-speech-arch/requirements-map-p0-hotfix.json --stage review --slice CORE --candidate c0d5a3d3 --repo .
=> FAIL: candidate mismatch; map candidate_commit must match --candidate
   FAIL: CORE-*: mandatory not ['VERIFIED'] (got PENDING)
   stage=review inventory=79 manual=81 scoped=8 errors=9
   EXIT=1
```

## 4. Блокирующие находки

### F1. BLOCKER — исправление мета-вступлений не проверено на кандидате
- **Где:** `plans/features/asap-speech-arch/evidence/p0-hotfix/probes_final2.md:5,9,78,103` (кандидат be24e28f, код 0428c271, §3 FAILED, 5/8); коммит `c0d5a3d3` меняет `services/prompt_style_blocks.py:245-253` и `services/direct_l1.py:1077-1084`, но evidence-файла `meta-fix.md` нет; `git show --name-status c0d5a3d3` не содержит evidence.
- **Наблюдение:** все 8 новых ответов 0428c271 начинаются с «Ох бля… Ладно, глянул…», «Да без проблем, сейчас разложу», «Давай посмотрим», «Давай разберём», «Давай разберёмся» — 5/8. Новая директива названа по этим же фразам, но ни один ответ после неё не сгенерирован.
- **Влияние:** владелец просил убрать мета-вступления; текущий кандидат это не доказал.
- **Минимальное исправление:** Builder — прогнать live A/B + forced тем же путём с harness кандидата (`e5a29e79…`), записать raw и первые предложения; критерий: 0/8 служебных преамбул. Не добавлять постпроцесс/обрезку.
- **Recheck:** тот же harness на сервере/стейджинге, sha harness = `e5a29e79…`, первые предложения в отчёте.

### F2. BLOCKER — авто-детектор меты слеп к одному из пяти наблюдавшихся типов
- **Где:** `plans/features/asap-speech-arch/evidence/p0-hotfix/probes_final2/analysis.json` (`new_code_A` L2#1 `meta=[]`, при тексте «Ох бля, Макс, ну ты даёшь запрос. Ладно, глянул твои сообщения…»); `probes_full/harness_probe_full.py:318-320` — regex только с начала строки и только по промптам; скрипт, сгенерировавший `analysis.json`, в репозиторий не закоммичен (`probes/harness_analyze.py` — другой, старый анализатор).
- **Наблюдение:** если следующий прогон будет опираться на `analysis.json.meta`, A1-тип («эмоциональная первая фраза + Ладно, глянул» во второй) снова даст ложный зелёный.
- **Влияние:** критерий §3 может быть формально закрыт при реальной преамбуле.
- **Минимальное исправление:** закоммитить анализатор L2, проверяющий первые 1–2 предложения/первый абзац на типы «ладно/ок/сейчас/давай/глянул/сейчас разложу/обещание разобрать» и на ярлыки (`**…:**`), с исключением цитат пользователя; добавить негативный контроль на старых raw (должен поймать A1, B2, forced A1/B1/B2) и положительный на новых.
- **Recheck:** анализатор на `probes_final2` даёт 5/8, на новом прогоне — 0/8.

### F3. BLOCKER — нет case C / короткого повседневного сообщения
- **Где:** `probes_full/harness_probe_full.py:479` (`choices=("A","B")`); `probes_final2.md:94` (проверка 8 NOT OBSERVED), `:104` (F4 GAP); `harness-case-c.md` отсутствует.
- **Влияние:** §1.4 прямо требует проверить «короткие повседневные сообщения»; проверка 8 остаётся непроверенной, а «краткость естественная» — недоказанной.
- **Минимальное исправление:** добавить `--case C` из реального окна (короткое бытовое сообщение), прогнать через тот же L2-путь; зафиксировать: L1 не форсирован, ответ короткий без обрезания, мета 0.
- **Recheck:** raw case C + первый абзац + длина.

### F4. BLOCKER (harness equivalence) — RAG-выборка неэквивалентна production
- **Где:** `probes_full/harness_probe_full.py:247` (`rows = sq.get("graph_facts")`); реальный сервис — `services/direct_chat_service.py:8521` (`get_rag_facts(chat_id, query, ...)` → `_search_graph_facts` KNN/MMR).
- **Наблюдение:** RAG-блок одинаков для A/B/forced A/B: `rag.block_sha12=1fdb8b237233`, 2027 симв., 39 строк — при разных вопросах. Production retrieval дал бы разный набор/ранжирование.
- **Влияние:** §1.2 запрещает принимать результаты в неэквивалентной конфигурации; участие RAG доказано, а реальный payload — нет.
- **Минимальное исправление:** в harness вызывать реальный `get_rag_facts`/`_search_graph_facts` с query (read-only PG), либо строить дамп per-query; записывать query и rows/ranks; перезапустить A/B.
- **Recheck:** блоки A и B различаются, rows приходят из реального retrieval, provenance-маркеры сохранены.

### F5. BLOCKER — паритетная фикстура P4 устарела; новый красный тест
- **Где:** `tests/fixtures/soul1/direct-runtime-assembly-asap2.txt:234-239` (`SYSTEM chars=8574 … 8ef75b632d12`); активный канон — 9288/`23aae0c9499d`; `tests/test_soul1_composer_parity_off.py:336-351`.
- **Воспроизведение:** `py -3 -m pytest tests/test_soul1_composer_parity_off.py::test_p4_l1_planner_system_matches_recorded_dump -q` → `AssertionError: P4: sha256_12 системы 23aae0c9499d != дампа 8ef75b632d12`.
- **База:** на `534ac7dd` этот тест PASS (4 других падения предсуществующие); на кандидате 5 падений. `core-full-writer-l1.md:81-86` ошибочно утверждает, что все 5 предсуществующие.
- **Влияние:** обязательный прогон красный; parity-дамп не отражает активный канон.
- **Минимальное исправление:** Builder — перегенерировать P4-секцию фикстуры из активного канона (9288, `23aae0c9499d`), обновить note/токены; не менять сам канон.
- **Recheck:** `pytest tests/test_soul1_composer_parity_off.py -q` → P4 PASS; остальные 4 — отдельно как предсуществующие.

### F6. BLOCKER (small, harness) — счётчик Core врёт
- **Где:** `probes_full/harness_probe_full.py:830-833` (`len(manifest.versions.core)`), `prompt_composer.py:1872` (`versions["core"] = core.revision`); `harness_probe_full.py:841` (`core_marker = "<Personality_Core>" in system`).
- **Наблюдение:** `raw_new_code_A.json` → `core.chars=0`, `system.core_marker=false`, при `layers[core].chars=3294` и реальном срезе 3294.
- **Влияние:** §1.2 требует честных счётчиков; поле выглядит как «Core отсутствует».
- **Минимальное исправление:** считать `core.chars`/`core_sha12` из `layers` (block_id=core) и/или среза system; убрать/исправить `core_marker`.
- **Recheck:** новый raw: `core.chars=3294`, `core_sha12=ead77b2ab509`.

### F7. Родительский gate (PM/Orchestrator) — карта не привязана к кандидату
- **Где:** `plans/features/asap-speech-arch/requirements-map-p0-hotfix.json` (`candidate_commit=""`, 79/79 PENDING, дубли `CORE-ACTIVE-VERIFIED`, `PROBES-TWO-RUNS`, `MEMORY-SELF-ECHO-REPEAT`, `MEMORY-NO-UNSUPPORTED-CAUSAL-STORY`); source карты — `source-owner-p0-hotfix-chained-2026-10-25.md`, а не corrective-источник; `l1-fix.md:111-118` уже фиксировал отсутствие HARNESS-строки.
- **Влияние:** release-gate `--stage review` не проходит; финальное DONE невозможно.
- **Минимальное исправление:** PM — привязать карту к corrective §1.1/§1.2/§1.4/§3, убрать дубли, проставить честные статусы (CORE/L1/FREQUENT VERIFIED; META/CASE-C/HARNESS — PENDING до прогона), затем recheck gate.
- **Recheck:** `requirements_gate.py check --stage review --slice … --candidate c0d5a3d3` → EXIT 0.

## 5. Некритичные наблюдения

- **N1. Лексический список в `NO_META_STRUCTURE_TEXT` — оверфит.** `prompt_style_blocks.py:245-253` перечисляет конкретные слова («ладно», «ок», «сейчас», «давай», «глянул»). Это prompt-инструкция, не фильтр, и семантическая часть («первое содержательное предложение — ответ») корректна. Но список покрывает не все наблюдавшиеся формы: A1 — «Ох бля… Ладно, глянул…», где запрещённое слово во второй фразе, а первая — эмоциональная подводка. Рекомендация: сохранить семантику, добавить тип «эмоциональный комментарий о запросе», не вводить постпроцесс/обрезку.
- **N2. Директива живёт только в plan-блоке.** В direct L2 план есть всегда (в т.ч. fallback-план), поэтому путь покрыт. Маршруты без plan-блока (инициативный fallback, функциональные writer'ы) директиву не получают — вне наблюдавшегося дефекта, но §3 сформулирован широко.
- **N3. Fallback-репак может выбросить plan-блок** (`direct_chat_service.py:4908-4912`), а с ним no-meta/analysis-тексты, при меньшем окне fallback-модели. Это существующее поведение, не новая квота; для основного пути не критично.
- **N4. `analysis.json` `in_ctx=false` цитаты** — гипотетические характеристики в кавычках, помеченные «в смысле/с позиции»; evidence объясняет. Не блокер.
- **N5. Тест Core читает snapshot `active-core.md`**, а не live DB; смена owner-Core не уронит тест. Авторитет — live-проба; snapshot привязан к 25.10.2026.
- **N6. `manifest.versions.core_detail` = null** в live raw — тот же дефект отчётности harness, что и F6.

## 6. Что проверено / переиспользовано

- **Новые проверки:** тесты кандидата (2 набора), harness self-check, независимая сборка Core композером, матрица no-meta (modes_on/off), сравнение базы 534ac7dd и кандидата, review-gate, чтение кода `chat_prompts/direct_l1/prompt_style_blocks/prompt_composer/prompt_registry/prompt_migrations/direct_chat_service`, разбор raw/analysis/manifest, проверка RAG-блока A/B, P4-диффа.
- **Переиспользовано:** live raw 0428c271 для Core/L1/FREQUENT (эти файлы c0d5a3d3 не меняет), с явной привязкой и без переноса no-meta-результатов.
- **Не выполнялось (boundary):** SSH/прод, Telegram, LLM-вызовы, правки кода. Внешние источники не требовались — все факты локальные.

## 7. Следующее действие

1. Builder: F1–F6 (код/тесты/harness), начиная с F5 (дешёвый красный тест) и F1/F2/F3/F4 (один live-прогон закрывает мету, case C и RAG-эквивалентность).
2. PM/Orchestrator: F7 — карта/ledger/gate.
3. Независимый Reviewer: новый exact candidate + новый live-прогон; до этого deploy не выполнять. Прод остаётся на 2.58.130 / `534ac7dd`.

**Evidence path:** `plans/features/asap-speech-arch/evidence/p0-hotfix/review-speech-core-l1.md`.