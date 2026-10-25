# L1 / harness audit — почему явный разбор истории уходит в casual/compact

- LANE_ID: **L1-HARNESS-AUDIT**
- Worktree: `C:\Code\Python\adminbot-wt-speech-p0`, HEAD `a97ba573`, ветка `task/speech-p0-hotfix`.
- Режим: **read-only**. Код, карты, `plans/current_task.md`, прод и Telegram не трогались; LLM-вызовов не было. Единственный исполненный код — локальный offline-пробник модулей (`response_extent`, `direct_l1`, `prompt_style_blocks`) без сети.
- Источник требований: `source-owner-p0-corrective-2026-10-25.md` §1.1 (исправить семантику выбора режима без хардкода слов; проверить и прямой выбор L1, и принудительный research) и §1.2 (harness из того же commit, честные счётчики, реальные payload с RAG/Memory/Core/Expression).

## 1. Итог в трёх причинах

| # | Причина | Где | Следствие |
|---|---|---|---|
| A | Активное правило 7 канона L1 приказывает «оценка человека/его поведения/чужого мнения» → `extent=normal|compact`, `structure=answer`, а `detailed/report` — только по явной просьбе **подробного разбора** | `services/chat_prompts.py:862-871` | «проанализируй мои сообщения» читается моделью как оценка человека → `answer/emotional_reply/banter` + `compact`; `research` не выбирается |
| B | В каноне нет ни одного положительного критерия `response_act=research`; `research` встречается ровно один раз — в enum схемы (`chat_prompts.py:656`). L1 видит только 20 сообщений + срез памяти (`direct_l1.py:644,662-714`) | `chat_prompts.py:647-695`, `direct_l1.py:644` | даже поняв «нужно исследовать историю», планер не имеет описанного способа это выразить и не видит материала для «глубокого» вывода |
| C | `response_act=research` **достаточен** для exact analysis/Writer-текстов, но `plan_response_mode()` отдаёт `casual` | `direct_l1.py:200-206,221-240,942-971` | тексты доезжают (plan-блок, 1×), но mode-метка и mode-блок для `research` без `report/rich` — «болтовня». Функционально не блокирует, семантически неверно |

Дефект **не** в payload-предикате и не в `MODE_DEEP_RESEARCH_BLOCK`: предикат на реальных планах отвечает корректно (0 текстов для `emotional_reply/banter`, 1× для `research`). Он не срабатывал потому, что L1 не выбирал `research`.

## 2. Причина A — правило 7 перекрывает исследование истории

Активные правила (`chat_prompts.py:862-871`, вставка в замороженные R3b через `.replace`):

```
7. Просьба оценить человека, его поведение или прозвучавшее о нём
   чужое мнение - это содержательный разбор по существу, а не заказ
   хроники, отчёта о событиях или биографии: extent=normal или compact,
   structure=answer. detailed и report выбирай только при явной
   просьбе подробного или полного разбора.
8. В ответе - ровно одна JSON-строка. Никакого текста вне JSON.
```

Что это делает с «проанализируй мои сообщения в чате, скажи, злобный ли я»:

1. Объект просьбы — человек и его поведение, значит правило 7 применимо.
2. Правило 7 прямо предписывает `normal|compact` + `answer` и запрещает `detailed/report` без отдельной просьбы «подробно».
3. `response_act` в этой ветке не назван вовсе, поэтому модель берёт ближайший «разговорный» акт: `emotional_reply` / `banter`.
4. Итог: `research` не выбран → `analysis_directive_needed=False` → в payload 0 точных analysis-текстов. Это **правильное** поведение кода при таком плане.

Реальные L1-планы (`probes_full.md:106-119`, 4 процесса, 8 raw):

| Кейс | response_act | extent | structure | mode | analysis-тексты в payload |
|---|---|---|---|---|---|
| old A | `answer` | normal | answer | casual | 0 (в old нет plan-блока) |
| new A | `emotional_reply` | compact | chat | casual | 0 |
| old B | `other` | auto | chat | casual | 0 |
| new B | `banter` | compact | chat | casual | 0 |

То есть новое правило 7 сделало маршрут **хуже** прежнего (`answer` → `emotional_reply`, `other` → `banter`): оно не только не дало `research`, но и добавило разговорную эмоциональную рамку. Метавступление в B#1 («ты хочешь, чтобы я проанализировал твои сообщения и сказал, злобный ли ты?») — прямое следствие того, что модель примеряет правило 7 к запросу на анализ.

Почему правило вообще появилось: жалоба владельца была на обратный дефект — простой вопрос «я злобный?» превращался в психологическое эссе. Правило защищает от эссе, но сформулировано через **объект оценки**, а не через **тип результата**, поэтому поглощает и заказ на исследование истории. Источник (`source-owner-p0-hotfix-addendum-2026-10-25.md:25,78`) требует обратного: «Сохранить… полноценную возможность подробного анализа пользователей», «При явном запросе подробного анализа бот способен отвечать подробно».

## 3. Причина B — у research нет описания и нет материала

- `response_act` объявлен открытым словарём (`direct_l1.py:59`), но в промпте это только перечисление значений (`chat_prompts.py:656`); ни `research`, ни `historical_recall`, ни `explanation` не описаны. Единственное правило про объём — правило 1: «длина сообщения не определяет extent» (ничего не говорит о том, когда нужен внутренний разбор).
- L1 получает `L1_WINDOW_MESSAGES = 20` (`direct_l1.py:644`) и «ПАМЯТЬ (срез)» (`direct_l1.py:712-713`). «Проанализируй мои сообщения» физически не выполнимо по 20 репликам; при этом в каноне нет указания, что при нехватке материала нужно запросить **существующую** возможность истории/памяти.
- Такие возможности уже есть и уже передаются планеру в списке доступных (`direct_chat_service.py:4268,4302`; `direct_capabilities.py:28-34`: `chat_history → get_recent_history`, `chat_memory → query_chat_memory`, `historical_search → dig_into_lore/compile_lore_story`). Правило 4 разрешает запрашивать только перечисленные — этого достаточно, новый слой не нужен.
- Важно: `research` сам по себе не увеличивает retrieval. `_build_rag_block(chat_id, message, global_ctx)` (`direct_chat_service.py:8403-8404`) не принимает план вовсе, т.е. состав RAG-фактов от `research` не зависит; дополнительный материал появляется только через `capabilities_needed` → tool loop → evidence pack (`direct_chat_service.py:4420`, `4521-4524`). Поэтому правило должно связывать «нужен материал за пределами окна» с существующей возможностью, иначе «глубокий анализ» останется рассуждением о 20 сообщениях — ровно тот дефект, из-за которого появился запрет на выдуманные связи.

## 4. Причина C — mode для research и как реально доезжают exact-тексты

Трасса (проверено локально, без LLM; `response_extent`/`direct_l1`/`prompt_style_blocks` из HEAD):

| План | mode | extent-блок | predicate | system AD | plan AD | payload AD |
|---|---|---|---|---|---|---|
| answer/normal/answer | casual | 141 | False | 0 | 0 | **0** |
| banter/compact/chat | casual | 112 | False | 0 | 0 | **0** |
| research/compact/answer | casual | 144 | True | 0 | 1 | **1** |
| research/normal/answer | casual | 141 | True | 0 | 1 | **1** |
| research/detailed/report | deep_research | 204 | True | 0 | 1 | **1** |
| research/auto/report | deep_research | 0 | False | 1 | 0 | **1** |

- `response_act=research` → `task_kind="research"` (`direct_l1.py:200-206`).
- `analysis_directive_needed` (`direct_l1.py:942-971`): для `deep_research` решает непустой extent-блок (`_renders_extent_block`, `:922-939`), иначе `act == "research" or kind == "research"`.
- `build_l2_plan_block(include_analysis=True)` кладёт дословные `ANALYSIS_DIRECTIVE_TEXT` / `ANALYSIS_WRITER_TEXT` в `<Response_Plan>` (`direct_l1.py:1044-1057`), а сервис добавляет блок в user-часть (`direct_chat_service.py:3757-3773,4773-4774`).
- Extent-блок **заменяет** `MODE_*_BLOCK` (`prompt_style_blocks.py:436-437`), поэтому для `research/compact` стиль «торопливое письмо» не применяется, а длину задаёт «ОЖИДАЕМАЯ ПОЛНОТА: КОМПАКТНО» (`response_extent.py:436-438`).

**Вывод по §2 задания:** `response_act=research` достаточно, отдельный `mode=deep_research` для exact-текстов **не нужен**. Ровно один экземпляр текстов обеспечен на всех ветках (1/1 в payload). Менять `plan_response_mode` не обязательно; полезная минимальная правка — считать `research` «serious», а не «casual» (`direct_l1.py:231-235`):

- плюс: честная mode-метка/лог и нейтральный mode-блок при `extent=auto`;
- **не** маппить research в `deep_research`: `_resolve_mode_block` читает PG-кастома `prompts.verbilizer_mode_deep_research` (`prompt_style_blocks.py:364`, `param_catalog.py:671`), где может лежать прежний блок «Выведи отчёт ПОЛНОСТЬЮ» — это вернуло бы дефект эссе;
- при непустом extent-блоке правка вообще не меняет payload (mode-блок вытеснен), поэтому её можно делать отдельно и она не является условием закрытия дефекта.

## 5. Предлагаемое семантическое правило (без списков слов)

Заменить правило 7 двумя правилами и сдвинуть JSON-дисциплину на 9 (текст для Builder; формулировка — смысловая, опирается на объект просьбы и тип результата, а не на конкретные фразы):

```
7. Смотри, что человек просит сделать с материалом, а не как он это называет.
   Если он хочет разобраться в уже сказанном - в сообщениях, переписке,
   собственных словах, отношениях или повторяющихся чертах - это
   исследование доступных сведений: response_act=research, и внутренний
   разбор может быть глубоким. Если он хочет только мнение, оценку или
   короткий вывод о человеке по текущему разговору, отвечай по существу:
   structure=answer, без хроники, биографии и отчёта.
8. Глубина разбора не задаёт длину ответа. Обычная просьба - compact или
   normal; явная просьба подробного разбора - detailed; полного отчёта -
   detailed или longform со structure=report. Если для ответа нужны
   сведения за пределами видимого окна, запроси доступную возможность
   истории или памяти из списка выше; если её нет - опирайся на видимое
   и не выдавай догадку за подтверждённое.
9. В ответе - ровно одна JSON-строка. Никакого текста вне JSON.
```

Что это сохраняет и почему не ломает quick opinion:

- «я злобный?» без материала о разговоре → ветка «только мнение/оценка/короткий вывод» → `answer`, без эссе: защита исходной жалобы сохранена.
- «проанализируй мои сообщения» → объект просьбы — уже сказанное → `research`; внешняя длина следует из §8 (обычно `compact`/`normal`, подробно — только по явной просьбе). Совпадает с corrective §1.1: «Подробная проверка истории может заканчиваться короткой репликой».
- Нет перечня триггеров: критерий — «что просят сделать с материалом» и «какой результат нужен»; тест запрещает появление литеральных фраз запроса в каноне.
- `detailed/report` больше не запрещены «по умолчанию» — они привязаны к явной просьбе объёма, как и раньше, но перестали быть единственным путём к глубокому разбору.
- Правила 1-6 остаются байт-в-байт; это уже принятая в проекте схема `.replace` (`chat_prompts.py:862`).

**Обязательная процедурная часть правки канона** (иначе ломается лестница отката, ADR-1013-3):

1. `PREV_DIRECT_L1_PLANNER_R3B` остаётся замороженным; добавить слепок текущих активных байтов (`PREV_DIRECT_L1_PLANNER_P0CS` = база R3 + контракт + continuation + правила с правилом 7) и собрать `DIRECT_L1_PLANNER_SYSTEM_PROMPT` из нового блока правил.
2. Лестницы миграций: в `PROMPT_MIGRATIONS` (`services/prompt_migrations.py:147`) прод-байты R3b должны вести на новый слепок, а новый слепок — на новый активный канон (шаг `R3b → P0CS → ACTIVE`, точное совпадение байт, кастомы владельца не перетираются; сейчас там `:235` `R3b → ACTIVE`). В `ROLLBACK_MIGRATIONS` (`:390`) верхняя ступень `prompts.direct_l1_planner_system_prompt` (`:423-430`) снимает только новую ступень → P0CS, прежние ступени целы.
3. Обновить пины правила 7: `tests/test_speech_p0_core_serious.py:228-253`, `tests/test_asap2_clar_contract.py:217`, `tests/test_asap_speech_r3b_canon.py:117`, `tests/test_direct_l1_corrective_r1.py:112-117`, `tests/test_direct_l1_l1d_contract.py:184`, `tests/test_prompt_migrations.py:290-292`.
4. Пересобрать прод-промпт штатной миграцией (канон — PG-значение; код-константа только дефолт).

## 6. Почему harness/счётчики/RAG расходятся

### 6.1 Три разные копии пробника

| Копия | Байт | sha256 |
|---|---|---|
| `/tmp/p0-full-new/probe_full.py` (staging new) | 23011 | `cea538c4df25…` |
| `/tmp/p0-probe/probe_full.py` — **исполненный** | 23055 | `3dcf602fa824…` |
| `probes_full/harness_probe_full.py` (репозиторий) | 23563 | `d0d510da847b…` |

Ни одна не совпадает. Исполненная копия обращалась к `direct_l1.analysis_directive_needed` напрямую (на old → `AttributeError`, `probes_full.md:90-93`), не выставляла `analysis_predicate` и не передавала `include_analysis`. Плюс `/tmp/p0-full-new/.git` отсутствует — версию дерева по git подтвердить нельзя (`executed_harness_note.md:1-25`). Требование §1.2 «harness из того же commit» не выполнено даже для new-плеча.

### 6.2 Гибридный план: system от одного плана, plan-блок от другого

`harness_probe_full.py:258-267` жёстко задаёт `response_mode`/`ResponsePlan` по кейсу (A = serious/research/normal/answer, B = deep_research/research/detailed/report) и собирает по нему system (`:356-373`). Затем `:405-439` вызывает **реальный** L1 и `:446-457` строит plan-блок **из реального плана**. В итоге:

- system несёт extent-блок выдуманного плана (отсюда 141 и 204 симв. в таблице `probes_full.md:57`),
- L2 отвечает по реальному плану (banter/compact, emotional_reply/compact),
- «payload» не соответствует ни одному реальному решению L1.

Это же объясняет, почему при исправном предикате текстов 0: реальный план не research, а выдуманный план в plan-блок не попадал.

### 6.3 Счётчики считают несуществующие литералы

- `harness_probe_full.py:389-390,464-465,474-475` — `count("ANALYSIS_DIRECTIVE")` / `count("ANALYSIS_WRITER")`: это ASCII-имена Python-констант, в русских текстах их нет. Их «0» ничего не значит (`repro_predicate.py`: `ascii_marker_in_text=false`).
- `:385-393` — `core_blocks = system.count("<Personality_Core>")`: литерала в коде нет (Core подаётся текстом), метрика всегда 0.
- `:392` — `mode_block = "MODE_DEEP_RESEARCH_BLOCK" in system`: имя переменной, всегда False.

### 6.4 RAG падает на dict-строках и молча деградирует

- Прод-контракт: `_build_rag_block` нормализует строки через `_rag_rows_with_ranks` в 7-кортежи (`direct_chat_service.py:1857-1885`), фильтрует self-origin (`:8460-8461`), ставит пометку достоверности (`:8510`), рендерит `build_rag_context(..., origin_labels=True)` (`:8511`), оборачивает в `<RAG_Memory>` и режет по `limits.graph_rag_context_max_chars` (`:8523-8535`).
- Пробник: `harness_probe_full.py:310-321` передаёт в `build_rag_context` **dict-строки** из SQLite. Внутри `build_rag_context` (`summary_memory.py:1408-1414`) идёт `item[0]`/`len(item)` → на dict это `KeyError: 0`. Отсюда `probes_full.md:95-98`: RAG отсутствует в A, пуст в B.
- Дополнительно: закоммиченная копия ловит исключение и подменяет рендер самодельными строками (`:316-321`, `rag_render="fallback_lines"`), т.е. «зелёный» результат может быть не прод-рендером. Исполненная копия до этой ветки не дошла (`rag_render` в raw отсутствует, ошибка в `stage_errors.rag`).
- В B `picked` пуст (нет пересечения по словам вопроса) — RAG не проверялся вовсе, хотя §1.4 corrective требует реальных payload с RAG/Memory.

### 6.5 User-часть собрана не как в сервисе

Порядок прод-сборки: `time_line → plan_block → speech/lessons (если композер OFF) → user_blocks → <Tool_Evidence>` (`direct_chat_service.py:4770-4784`), при ON — те же части как защищённые (`:4815`). Пробник: `rag → <Chat_Summary> → plan_block → Target_User → Global_Context → Current_Question` (`harness_probe_full.py:467-472`), без `time_line`, lessons (они только в system), evidence и без `user_parts` в композер (`:373`). Для поведенческой пробы это допустимо, для утверждения «фактический payload» — нет.

## 7. Как получить реальный payload из того же commit (минимальные правки пробника)

Никакой новой архитектуры; всё через существующие функции целевого дерева.

1. **Пин версии.** `git -C <root> rev-parse HEAD` + `git status --porcelain` + sha256 файлов импортированных модулей в результат; запуск **из самого worktree** (без staging-копии без `.git`). Копия, исполняемая на сервере, должна иметь тот же sha256, что закоммиченная.
2. **Один план на весь payload.** Сначала реальный L1 → `parse_l1_plan`, затем `response_mode = plan_response_mode(plan)`, `response_plan = plan.to_response_plan()`, `extent_block = render_extent_block(response_plan)`, `plan_block = build_l2_plan_block(plan, include_analysis=analysis_directive_needed(plan, modes_on=...))`, и **эти же** объекты — в `_compose_speech_system(response_mode=..., response_plan=..., extent_block=...)`. Принудительный research — отдельный явно помеченный сценарий (`--force-plan research`, `forced=true`), не подмена реального решения.
3. **Честные счётчики.** Считать `psb.ANALYSIS_DIRECTIVE_TEXT` / `ANALYSIS_WRITER_TEXT` в трёх местах: `system`, `user_text`, `system + "\n\n" + user_text`; писать `analysis_predicate` и `plan_source` (`llm|fallback|forced`). Инвариант: `payload == 1/1` для research; `payload == 0/0` для не-research без `include_analysis`. Удалить ASCII/имя-переменной счётчики.
4. **Реальный RAG.** `facts, ranks = DirectChatService._rag_rows_with_ranks(rows)` → фильтр `_prov.is_self_referential_origin(f[0])` → `dedup_rag_vs_global` → `_mark_rag_fact` → `build_rag_context(order_rag_facts_asc(kept), origin_labels=True)` → `<RAG_Memory>` + cap. Ошибку рендера считать **невалидным прогоном** (`invalid="rag_render"`), а не подменять строками.
5. **User-часть порядка сервиса** и `user_parts=tuple(parts)` в композер; фиксировать `user_sha256`, длины, `expression_marker`, `core_sha12` из манифеста слоёв. Никаких срезов при подсчёте.
6. **Симметрия old/new.** Один и тот же файл (равный sha256) исполняется на оба дерева; в обоих raw писать `commit`, `code_sha`, `forced`, `invalid`.

## 8. Минимальные тесты (предложение Builder)

| Тест | Класс | Что доказывает |
|---|---|---|
| `tests/test_speech_p0_corrective_l1_route.py::test_l1_canon_separates_material_from_opinion` | CONTRACT | активные правила содержат обе ветки (§7: исследование уже сказанного → `research`; мнение/оценка → `answer` без эссе) и не содержат литеральных фраз запроса как триггеров |
| `...::test_l1_prev_snapshot_is_previous_rule_bytes` | CONTRACT | `PREV_DIRECT_L1_PLANNER_P0CS` == прежние активные байты; ACTIVE != PREV; цель отката указывает на новый слепок; R3b не изменён |
| `tests/test_speech_p0_core_serious.py::test_research_compact_payload_has_exact_texts_once` | REGRESSION | forced `research/compact/answer`: predicate True, extent-блок есть, в полном payload ровно 1×1 текстов; `answer/compact` → 0×0 (короткий повседневный ответ) |
| `...::test_research_auto_keeps_single_mode_source` | REGRESSION | `research/auto`: тексты ровно 1× в system (режимный блок) и 0 в plan-блоке; после правки mode-метки (`research → serious`) дубля по-прежнему нет |
| `...::test_analysis_texts_do_not_impose_length` | CONTRACT | в `ANALYSIS_*_TEXT` нет приказов объёма («полностью», «полный отчёт»), т.е. глубина не задаёт длину (§1.1 corrective) |

Плюс не-pytest: `python harness_probe_full.py --self-check` — на синтетическом research-плане проверяет, что счётчик равен 1 для `ANALYSIS_DIRECTIVE_TEXT` и 0 для литерала `ANALYSIS_DIRECTIVE`; прогон с `--self-check` обязателен перед серверным сеансом. Тест-портфель не расширять сверх этого: остальное уже покрыто `test_speech_p0_core_serious.py:115-223` и `test_speech_p0_hotfix_texts_analysis.py:143-171`.

## 9. Границы этого аудита

- LLM не вызывался: вывод о причине A опирается на 4 **реальных** L1-плана из `probes_full.md:106-119`, а не на новый живой прогон. После правки канона нужен именно живой L1-прогон (прямой выбор) + один forced-research сценарий — §1.1 corrective.
- Payload-числа §4 получены локально на HEAD тем же кодом, что исполняет `_l2_write_answer` (композер + предикат + план-блок), без сети и БД; RAG/Core/Expression в них не входят — это закрывает только плечо exact-текстов.
- Прод не проверялся; 13 изменённых файлов прод-дерева и алиасы — вне этого лейна (§1.3/§2 corrective).
- `requirements-map` для corrective ещё не создан (это работа PM); здесь только инженерные факты и предложения.
