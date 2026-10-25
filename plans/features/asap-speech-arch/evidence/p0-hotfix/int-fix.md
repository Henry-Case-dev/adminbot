# P0 SPEECH — интеграция исправлений ревью (F2–F6)

- **LANE:** `SPEECH-INT-FIX`, один писатель, worktree `C:\Code\Python\adminbot-wt-speech-int`,
  ветка `task/p0c-int`.
- **Кандидат:** `fe1e514a` (merge `505c0422` + F2/F4/F5/F6 + фикс стенда
  UnboundLocalError + R2 §9: L1-канон, исполнимая мета, пустой RAG;
  docs-коммит сверху код и тесты не меняет).
- **База сравнения:** `534ac7dd` (прод 2.58.130).
- **Источник:** `review-speech-core-l1.md` (скопирован в это дерево), блокирующие находки F2–F6.
- **Вердикт по моей части:** все F2–F6 закрыты кодом/данными; живой прогон
  (A/B/C + реальный RAG на сервере) остаётся за DevOps — локально в этом
  worktree нет `.env` и `local_database.db`, стенд честно падает на этом.

## 1. Merge `4403b1b6` → `task/p0c-int` (`505c0422`)

Конфликт был один — `probes_full/harness_probe_full.py` (self-check). Разрешён
**объединением обоих наборов**, ничего не выброшено:

| Источник | Проверки |
|---|---|
| `c0d5a3d3` | `no_meta_research_plan_once`, `no_meta_casual_plan_once`, `no_meta_deep_auto_mode_once`, `meta_phrases_absent_from_prompts` + `meta_check` в отчёте |
| `4403b1b6` | `no_meta_directive_1x1_research`, core_report×4, case A/C×4 + `answer_payload`, `core_report`, `case_inputs` в отчёте |
| новое | `no_meta_directive_1x1_answer`, `meta_detector_catches_second_sentence`, `meta_detector_clean_answer`, `rag_service_*`×4, `rag_dump_marked` |

Два места, где простое объединение дало бы ложный результат, исправлены по существу:

1. **`no_meta_directive_0_answer` (4403) противоречил контракту `c0d5a3d3`.**
   После `c0d5a3d3` директива едет в plan-блоке ЛЮБОГО direct-ответа (мета-вход
   запрещён и в обычном ответе). Проверка «0 на обычном ответе» была бы вечно
   красной, а рантайм-инвариант `_need = 1 if (include_analysis or deep)` —
   вечно `invalid=no_meta_invariant`. Заменено на честное `1x1` в plan-части:
   `answer_payload.user.no_meta == 1 and answer_payload.system.no_meta == 0`.
2. **Рантайм-инвариант no-meta теперь считается по фактическому носителю**:
   `carrier = mode_block | plan_block | none`; `deep_research` с extent-блоком и
   `modes_on` — режим несёт директиву, иначе её несёт план. И `_run` передаёт
   реальный `modes_on` в `build_l2_plan_block` (сервис делает то же в обоих
   L2-путях, `direct_chat_service.py:3770,9228`), иначе на modes-off стенд
   расходился с продуктом.

```
py -3 probes_full/harness_probe_full.py --self-check  => PASS, 37/37 checks
(31 базовая проверка merge/детектора/RAG + 3 AST-guard + 3 rag_source)
code_l1_canon = 9288 / 23aae0c9499d
```

(В `--self-check` пишется и `git.commit/dirty`; для живого прогона требуется
`dirty=false` — эта строка снимается на сервере, локально evidence-файл сам
делает дерево грязным.)

## 2. F2 — детектор мета-вступлений (закоммичен)

`probes_full/analyze_l2_meta.py`. Прежний `analysis.json` считал `meta=[]` для
«Ох бля… Ладно, глянул…», потому что regex требовал совпадения с начала строки.
Новый детектор:

* окно — **первые 1–2 предложения первого абзаца** (+ первый блок для ярлыков);
* три **раздельные** категории: `announce` (анонс действия), `leadin`
  (служебная подводка), `label` (отчётный ярлык `**Вердикт:**`, `Итог:`, `# …`);
* цитаты пользователя вырезаются до сопоставления (замена той же длины);
* эмоциональная реакция на запрос («Ох бля, ну ты даёшь запрос») сама по себе
  метой не считается — иначе положительный контроль стал бы фиктивным.

**Негативный контроль (закоммиченные raw прогона 0428c271) — ровно известные 5/8:**

```
py -3 probes_full/analyze_l2_meta.py --glob ".../probes_final2/raw_new_*.json"
raw_new_code_A.json   flagged=1/2  #0 announce+leadin: «Ладно, глянул твои сообщения…»
raw_new_code_B.json   flagged=1/2  #1 announce+leadin: «Да без проблем, сейчас разложу.»
raw_new_forced_A.json flagged=1/2  #0 announce+leadin: «Давай посмотрим.»
raw_new_forced_B.json flagged=2/2  #0 «Давай разберём.»  #1 «Давай разберёмся.»
TOTAL 5/8
```

Отдельно: **тип A1 (анонс во ВТОРОМ предложении) теперь ловится** — это и был
слепой участок (`#0 announce: Ладно, глянул твои сообщения…`).

**Положительный контроль — 3 чистых ответа того же прогона + эталонные строки:**

```
raw_new_code_A #1 «Бля, Макс, ну ты сам подумай. Ты единственный, кто вступился…»  ok
raw_new_code_B #0 «Да ты ебанулся, Макс. Я тебе уже сказал — он не злобный…»      ok
raw_new_forced_A #1 «Бля, Макс, ну ты сам-то как думаешь? Ты тут сидишь…»          ok
POSITIVE_SAMPLES (4 строки, включая «Бля, Макс, ты серьёзно?»)                     0 категорий
```

`--self-check` (PASS): `positive_clean_samples`, `negative_known_five`
(«лишнее» срабатывание = FAIL, не только пропуск), `type_announce`,
`type_leadin`, `type_label`, `type_clean`.

Стенд теперь сам считает мету на каждом L2-ответе (`result["l2_meta"]`:
`flagged/total`, категории, окно, sha анализатора), поэтому живой прогон даёт
`0/8` или `5/8` машинно, а не на глаз. Регрессия закреплена
`tests/test_speech_p0_meta_detector.py` (5 проверок, CONTRACT).

## 3. F3 — case C (из merge) и A/B

`--case C` — короткая бытовая реплика «Слушай, а ты дождь любишь или тебя от
него тоже ломает?» как следующее сообщение в том же окне/точке времени, что A;
`question_source=synthetic_case_c`, по умолчанию **1** L2-вызов (A/B — 2).
Маршрут не навязан: если L1 скажет `research` — это находка, а не сбой стенда.

Проверено офлайн (self-check): `case_a_unchanged` (A/B читают реальное сообщение
из БД, `question_source=db`, те же `target_ts`/`tg_id`), `case_c_synthetic`,
`case_c_same_window_as_a`, `case_c_short_single_line`.

**Честная граница:** «проходит L1 → payload → 1 L2-вызов» и «A/B байт-в-байт» на
данных проверяются только живым прогоном (нужны `.env` + БД). Локальный запуск
`--case C --out x` доходит до первого шага и честно падает:
`fatal: FileNotFoundError .env` — тихого зелёного нет.

## 4. F4 — RAG: реальный путь сервиса вместо дампа 40 строк

Было: стенд сам собирал блок из `SELECT … LIMIT 40` (39 строк, 2027 симв.,
одинаковый для A/B/B-forced — `1fdb8b237233`). Стало: вызывается **та же функция
продукта**, что в проде:

```python
service = DirectChatService.__new__(DirectChatService)
service.memory = _RecordingMemory(real_memory)     # реальный MemoryManager
block, hint = await service._build_rag_block(CHAT_ID, _RagMessage(question), window_text)
```

Эквивалентность доказывается структурно и данными, а не пересказом:

| Что | Как проверено |
|---|---|
| та же функция | `rag_service_function_real`: `type(svc)._build_rag_block is DirectChatService._build_rag_block` |
| те же фильтры/аргументы retrieval | `rag_service_retrieval_kwargs`: `get_rag_facts(chat_id, query, include_direct_reply=True, include_self=True, with_meta=True)` — прод-вызов `direct_chat_service.py:8521` |
| query — реальный запрос хода | `rag_service_query_passed` + `rag.retrieval_call.query` в каждом raw |
| тот же порядок/фильтр self/dedup/ранги/cap | логика НЕ дублируется в стенде: self-origin фильтр, `dedup_rag_vs_global`, реранк, `order_rag_facts_asc`, `_mark_rag_fact`, per-chat cap — исполняется код продукта |
| данные retrieval | `rag.retrieval_call.rows / ids / rows_sha12 / ranks` — видно, что A и B получают РАЗНЫЕ наборы |
| backend памяти | реальная `MemoryManager` над `DatabaseService.initialize_readonly()` (`mode=ro`); `vec_reflected` показывает, что KNN-ветка доступна по фактической таблице снимка |

`DatabaseService.initialize_readonly()` не пишет; `touch`/`resurrect`-записи в
продуктовом коде обёрнуты в try/except и на текущий состав/порядок ответа не
влияют (проверено чтением `summary_memory.py:4382,4548,4626`).

**Fallback только явный:** без БД/сбоя — `rag_source=dump` + `dump_reason`.
Фактический вывод локально:

```
source=service -> rag_source=dump reason=реальный путь недоступен: FileNotFoundError: local_database.db отсутствует в --root
source=dump    -> rag_source=dump reason=реальный путь недоступен: задан --rag-source dump
```

То есть тихой подмены нет, и в отчёте всегда видно, чем собран RAG.

**Проверка полного пути `build_rag_block(source=service)`** (подменён ТОЛЬКО
backend памяти — БД в этом worktree нет; вся сборка блока — код сервиса):

```
[A] rag_source=service rows=2 empty=False
    call={"chat_id": -1002661910336, "query": "что за фигня с Костей?",
          "kwargs": {"include_direct_reply": true, "include_self": true,
                     "with_meta": true}, "rows": 2, "ids": [11, 12],
          "rows_sha12": "7b93b0c58cf4", "ranks": {"0": 2}}
    block_sha12=f2c3717f483a chars=93
    block='<RAG_Memory>\n[чат] [10.2026 | tg:42]: (не подтверждено) Макс вступился за Костю\n</RAG_Memory>'
    self-origin ('bot_self_reply', id 12) отброшен самим сервисом: True
[B] rag_source=service rows=1 empty=False
    call={"chat_id": -1002661910336, "query": "а Ринтаро что?", ... "rows": 1, "ids": [21],
          "rows_sha12": "cca90231afa7", "ranks": {"0": 1}}
    block_sha12=b206ce1b4946
A==B block: False
```

Здесь видно всё, чего не хватало прежнему дампу: query доходит до retrieval,
наборы A и B разные, self-выводы отфильтрованы продуктовым предикатом, пометка
достоверности поставлена продуктовым `_mark_rag_fact`.

**Честная граница:** KNN+MMR на реальном снимке и различие блоков A/B
подтверждаются живым прогоном (нужны БД + embed-ключи; `_make_llm` теперь
передаёт `EMBEDDING_*` из `.env`, иначе retrieval молча ушёл бы в FTS-fallback).

## 5. F5 — устаревшая P4-фикстура (регрессия закрыта)

`tests/fixtures/soul1/direct-runtime-assembly-asap2.txt`, секция P4:

```
было:  SYSTEM chars=8574  tokens=2144 sha256_12=8ef75b632d12   (канон R3-эпохи)
стало: SYSTEM chars=9288  tokens=2322 sha256_12=23aae0c9499d   (активный канон)
       USER   chars=528   tokens=132  sha256_12=533922cac0eb   (не менялся)
```

Регенерация не «подгонкой цифр»: скрипт прогнал реальный `_plan_direct_l1` через
`StubLLM`, взял фактически отправленный system/user, сверил
`system == DIRECT_L1_PLANNER_SYSTEM_PROMPT` (9288/`23aae0c9499d`) и
`user ==` прежнему телу фикстуры, и записал эти байты. Заметки секции обновлены
под активные правила 7/8. Повторный прогон идемпотентен (0 diff). Тест не
ослаблен: по-прежнему сравнивает chars/tokens/sha256_12 дампа.

```
py -3 -m pytest tests/test_soul1_composer_parity_off.py::test_p4_l1_planner_system_matches_recorded_dump -q
=> 1 passed   (на 534ac7dd тоже passed: там канон совпадал со старой фикстурой)
```

## 6. F6 — честные счётчики Core

`core.chars/sha12/rendered/in_system` берутся из отрендеренного слоя
`layers[block_id="core"]` и проверяются на вхождение в финальный system
(`core_report`); `versions["core"]` остаётся только ревизией.
`core_marker` удалён — литерала `<Personality_Core>` в payload нет ни в одном
дереве, поле всегда было `false` и читалось как «Core отсутствует».
Self-check: `core_report_chars / _revision / _in_system / _sha12` — PASS.

Живой raw подтвердит `core.chars=3294`, `core_sha12=ead77b2ab509` (в прогоне
0428c271 это уже было верно в `layers`, но отчёт печатал 0).

## 7. Тесты: кандидат vs база `534ac7dd`

| Набор | База 534ac7dd | Кандидат e0a46414 |
|---|---|---|
| `pytest <обязательный набор 1>` | 4 failed, 61 passed (3 существующих файла; `test_speech_p0_*.py` на базе ещё нет) | **4 failed, 84 passed** (5 файлов) |
| `pytest tests -k "speech_p0 or direct_l1 or prompt or composer"` | 8 failed, 738 passed | **4 failed, 804 passed** |

Красные на кандидате — те же 4, что и на базе (предсуществующие, не мои):

```
tests/test_soul1_composer_parity_off.py::test_tool_phase_on_equals_legacy_tail_without_new_layers
tests/test_soul1_composer_parity_off.py::test_tool_phase_on_and_off_scrub_identically_on_longform
tests/test_soul1_composer_parity_off.py::test_l2_on_keeps_block_set_and_applies_designed_order
tests/test_soul1_composer_parity_off.py::test_l2_on_without_plan_keeps_mode_block
```

Причина у всех четырёх одна и та же и на базе, и на кандидате: ON-контур
добавляет `<Speech_Base>`-хвост, которого нет в легаси-склейке, с которой
сравнивает тест (`assert manifest_system == legacy`). К P0-правкам отношения не
имеет; чинить в этой полосе — расширение скоупа.

Дополнительно: 4 красных базы `tests/test_quota_removal_composer.py::test_long_instructions_reach_payload_whatever_env_says[*]`
на кандидате **зелёные**. Механизм проверен: на базе `simplify_core_for_prompt`
менял текст ядра (8413 → 8412 симв., `strip`), поэтому длинная инструкция не
доходила до system байт-в-байт; на кандидате функция — identity, слой
`core.chars=8413`. Это улучшение контракта «инструкции не обрезаются», а не
новая квота: новых лимитов/обрезок в диффе нет.

tests/test_speech_p0_meta_detector.py — 5 passed.
Новый файл тестов гарда: `tests/test_speech_p0_harness_guard.py` — 4 passed.

## 8. Harness UnboundLocalError fix (блокер живого прогона `e0a46414`)

**Симптом (production-прогон, `probes_final3.md`):** RAG-вызов падал с
`UnboundLocalError`, `invalid=rag_render`, `rag_source=dump`, `block_chars=0`,
`l2_chars=[]` — L2 не вызывался вообще. `--self-check` был зелёным.

**Причина.** В `_run` вызов `build_rag_block(..., llm=llm, ...)` стоял на
строке 1030, а единственное присваивание `llm = _make_llm(...)` — на 1072.
Python считает имя локальным, если оно присвоено ГДЕ УГОДНО в функции, поэтому
чтение до присваивания — `UnboundLocalError`, а не `NameError` из внешней
области. Мой `except Exception` вокруг RAG переводил это в помеченный `dump` и
останавливал прогон по `invalid` — то есть ошибка была видна в JSON, но
`--self-check` её не воспроизводил, потому что `_run` не вызывает.

**Фикс (без заглушек, без изменения продукта):**
1. `llm = _make_llm(args.root, result)` поднят НАД первым использованием — сразу
   перед сборкой RAG (строка 1214), позднее присваивание удалено. Клиент
   создаётся после `hot.set_config_cache(...)` (1145), поэтому embed-настройки
   берутся из реальных PG-settings, как в проде.
2. Добавлен детерминированный AST-guard `unbound_local_findings(source)`:
   находит имена, прочитанные в функции раньше первого присваивания; учитывает
   параметры, `global`/`nonlocal`, вложенные функции/лямбды/классы и включения
   (своя область) — поэтому не даёт ложных срабатываний.
3. Guard в `--self-check`: `no_use_before_assignment` (реальный файл стенда),
   `unbound_guard_catches_pattern` (образец с дефектом обязан дать ровно
   `llm`), `unbound_guard_clean_pattern` (корректный образец — чисто).
4. Отдельный вход `--ast-check FILE` — проверка любого файла, exit 1 при находках.
5. `rag_source` в отчёте: верхнеуровневое `result["rag_source"]` +
   `run_summary().rag_source` берутся из фактического `rag.rag_source`
   (`service`/`dump`); если данных нет вовсе — пишется `unreported`, никогда
   `null`. Сводка печатает источник и `dump_reason`.
6. Невалидный/фатальный прогон теперь возвращает **exit 1**
   (`RUN_INVALID=<причина>` в stderr), а не 0 — «зелёного» вида у сломанного
   прогона больше нет.

**Доказательство, что guard ловит старую версию (и не ломает новую):**

```
$ py -3 probes_full/harness_probe_full.py --ast-check <старый e0a46414>
_run: 'llm' читается стр. 1030, присваивается стр. 1072
ast_check ...\old_harness.py findings=1
exit=1

$ py -3 probes_full/harness_probe_full.py --ast-check probes_full/harness_probe_full.py
ast_check ...\probes_full\harness_probe_full.py findings=0
exit=0
```

(старый файл получен как `git show e0a46414:probes_full/harness_probe_full.py`.)

```
py -3 probes_full/harness_probe_full.py --self-check  => PASS, 37/37 checks
unbound_guard.file_findings = [] , bad_sample = ['llm'], harness = <abs path>

py -3 probes_full/harness_probe_full.py --case C --out dry.json
=> fatal: FileNotFoundError .env; RUN_INVALID=... ; exit=1
   summary: "rag_source": "unreported", "rag": {"rag_source": "unreported"}
```

Регрессия: `tests/test_speech_p0_harness_guard.py` (4 проверки) — реальный файл
чист, образец дефекта ловится, корректный порядок/области не флагуются,
`rag_source` в сводке равен фактическому пути и никогда не `null`.

Наборы тестов после фикса: `4 failed, 84 passed` (набор 1) и
`4 failed, 808 passed` (набор 2) — те же 4 предсуществующих падения паритета,
что и на базе `534ac7dd`.

## 9. Живой прогон `67ff463c` — R2: L1-канон, исполнимая мета, пустой RAG

Источник — `probes_final4.md` (кандидат `67ff463c`, 7 прогонов, `invalid` пусто).
Три пункта приёмки не выполнены: L1 natural A/B = `answer`/`hostile_rebuff`
(0/2 research), мета 2/8, `rag.block_chars=0` при `rag_source=service`.

### 9.1 A. L1 — почему один канон давал то research, то answer

**Диагноз (три независимые причины, все проверены по коду):**

1. **Открытый словарь `response_act` без нормализации.** `_clip_word` принимал
   любое слово: `analysis`, `review`, `разбор` оставались собой, а вся
   маршрутизация сравнивает `act == "research"` (`direct_l1.py:972`). Синоним
   молча выключал analysis-директиву и Writer — без ошибки и без лога.
2. **Формулировка правила 7 ставила триггер вторым.** В редакции 2 разбор
   вводился условием «если он хочет разобраться в уже сказанном», а последняя
   фраза правила отдавала «мнение/оценку» в `answer`. Запрос A заканчивается
   вопросом-оценкой, поэтому модель легально разрешала конфликт в пользу
   `answer` (recency внутри правила).
3. **Не было исключения враждебных актов.** B просил разобрать переписку
   третьего лица; модель прочитала это как выпад и вернула `hostile_rebuff`
   (валидное значение канона, никакой ошибки).

**Исправление:**

* `direct_l1.canonical_response_act()` + таблица `RESPONSE_ACT_ALIASES` —
  детерминированное отображение известных форм к канону
  (`analysis/analyse/analyze/review/investigation/разбор/анализ/deep_analysis…`
  → `research`; `summary`→`summarization`; `history`→`historical_recall` …).
  Незнакомое слово сохраняется как раньше — словарь остаётся открытым,
  угадывания по смыслу нет. Нормализация вызывается из `normalize_l1_plan`.
* Правило 7 переписано (без списков фраз запроса): просьба разобрать,
  проанализировать, просмотреть, сравнить или обобщить сообщения/переписку/
  историю/собственные слова — это `research`, и это так **даже при добавленном
  в конце вопросе-оценке** (оценка — вывод разбора). Оценка без разбора
  материала остаётся `answer` (`structure=answer`); просьба разобрать материал
  «не является выпадом в адрес бота» и не выбирает `hostile_rebuff/banter/
  disagreement`.
* Ступень миграции: `PREV_DIRECT_L1_PLANNER_P0CINT` = ровно прежние активные
  байты живого прогона (9288/`23aae0c9499d`); `PROMPT_MIGRATIONS` и
  `ROLLBACK_MIGRATIONS` получили новый шаг; активный канон —
  9391/`ca1ba3049991`; отпечаток реестра `FACTORY_SET_SHA256_12`
  `ffc36e1c66db` → `50492308595e` (переутверждено осознанно, метка
  `l1-planner-material-first`).

**Синтетические L1-кейсы (без LLM, детерминированно)** —
`tests/test_speech_p0_l1_canonical.py` (27 проверок):

```
{"response_act": "analysis"}  → research  → analysis_directive_needed=True,
                                            plan_block несёт «как разбирать:»
{"response_act": "разбор"}    → research  → True
{"response_act": "review"}    → research  → True
{"response_act": "answer"}    → answer    → False (analysis-блока нет)
{"response_act": "brand_new_act"} → brand_new_act (словарь остался открытым)
```

Плюс проверки канона: правило 7 содержит `response_act=research`, «разбор
материала», «вопрос-оценка», «оценка - вывод разбора», исключение
`hostile_rebuff`; `structure=answer` для ветки без материала; правило 7 стоит
до 8; литеральных фраз запроса («проанализируй мои сообщения», «я злобный»,
«в чате») в каноне нет.

**Честная граница:** сам выбор модели (research vs answer) доказывается только
живым прогоном; тесты доказывают, что (а) любой research-синоним больше не
теряется и (б) канон содержит требуемую семантику. Для следующего raw добавлено
поле `l1_act_raw` / `l1_act_normalized` / `l1_act_rewritten` — видно, был ли
синоним.

### 9.2 B. Мета — почему директива не удерживала

**Диагноз.** `NO_META_STRUCTURE_TEXT` доезжал ровно 1× (payload-инвариант
подтверждён), но лежит в plan-блоке — в НАЧАЛЕ user-части. Дальше идут
`Global_Context`, `Target_User` и `Current_Question`, поэтому последнее, что
читает Writer, — сам вопрос, а не ограничение (recency). Отсюда «Давай
посмотрим на твои сообщения в этом чате.» (newA#1) и «Давай, разложу.»
(new_forced_B#0).

**Исправление (без квот и без обрезки):**
* `prompt_style_blocks.NO_META_CLOSING_TEXT` — короткое ПОЛОЖИТЕЛЬНОЕ
  требование: «Первое предложение ответа - сразу суть: вывод, факт или прямой
  ответ. Начинай с самого разбора…». Длина, формат и схема не задаются,
  постобработки нет.
* `direct_chat_service._l2_write_answer`: требование добавляется ПОСЛЕДНИМ
  блоком user-содержимого (после `Current_Question` и `Tool_Evidence`), ровно
  один раз; основная директива остаётся в plan-блоке. Если блоков нет —
  user-часть по-прежнему начинается с самого вопроса (прежний fallback цел),
  требование идёт после него.
* Зеркально в стенде (`_run` строит тот же порядок) + счётчик `closing` и
  инвариант `invariant_closing_1x1`; `--self-check` проверяет, что требование
  последнее и после `</Current_Question>` и в system его нет.

Тесты: `tests/test_speech_p0_meta_closing.py` (4) — порядок, ровно 1×, вне
system, plan-директива на месте, для `answer` нет analysis-текстов, текст
требования положительный и без квот/схем. Плюс существующий инвариант 1×1
analysis-текстов (`test_speech_p0_corrective_l1_route.py`).

### 9.3 C. RAG — пустой блок объяснён, а не «сломан»

**Что было.** `rows=10`, наборы A/B разные, `vec_reflected=true`, но
`block_chars=0`: raw не писал ни origin'ов, ни промежуточных счётчиков, поэтому
причину нельзя было назвать (инфраструктурная находка §10.3 отчёта).

**Что добавлено.** `_rag_service_diagnostics()` прогоняет те же ПРОДУКТОВЫЕ
функции (`_rag_rows_with_ranks`, `is_self_referential_origin`,
`dedup_rag_vs_global`) по тем же строкам и пишет в raw:

```
rag.after_self_filter, rag.after_dedup,
rag.rows_detail = [{id, origin, self_referential, kept_after_dedup, rank, expired}],
rag.rag_empty_reason = no_facts | all_self_origin | dedup_vs_global |
                       service_empty | rendered,
rag.rag_empty_is_correct = true для no_facts/all_self_origin
```

Пустой блок больше не считается поломкой сам по себе: если все строки —
собственные выводы бота (`bot_self_reply`/`bot_direct_reply`), P0-правило
self-echo требует именно пустого RAG, и это помечается машинно. Защита
self-echo не ослаблена ни на строку.

**Локальное воспроизведение на 10 строках** —
`tests/test_speech_p0_rag_diag.py` (5):

```
10 × bot_self_reply        → block="" , after_self_filter=0 ,
                             reason=all_self_origin, is_correct=true
6 facts + 4 bot_direct_reply → block непустой, after_self_filter=6,
                             «бот ответил…» в блок не попал
3 facts, дубли в global_ctx → block="", after_self_filter=3, after_dedup=0,
                             reason=dedup_vs_global, is_correct=false
0 строк                    → reason=no_facts, is_correct=true
```

Точный ответ для живого прогона даст следующая матрица: `rows_detail` назовёт
origin каждой из 10 строк. Если причина `all_self_origin` — критерий
`block_chars>0` для этого чата надо переформулировать (Reviewer), а не
«чинить» фильтр; если `dedup_vs_global` — это отдельный диагноз.

### 9.4 Инфраструктура стенда (не продукт)

Процесс после сводки больше не висит: JSON пишется и закрывается, затем
`_exit_now()` (flush + `os._exit`) — иначе `aiosqlite`/`asyncpg` держали
не-daemon потоки, и `timeout 900` съедал 15 минут на кейс (`probes_final4.md`
§10.1). Невалидный прогон по-прежнему завершается exit 1 с `RUN_INVALID=`.

### 9.5 Тесты: delta против предыдущего кандидата `67ff463c`

| Набор | `67ff463c` (до правки) | этот кандидат |
|---|---|---|
| обязательный набор 1 (5 файлов) | 4 failed, 84 passed | **4 failed, 84 passed** |
| `tests -k "speech_p0 or direct_l1 or prompt or composer"` | 4 failed, 808 passed | **4 failed, 844 passed** |
| полный `tests` (без UI-e2e) | 33 + 4 = 37 в тех же файлах | **37 failed, 15749 passed** (те же) |
| новые целевые файлы (4) | — | **44 passed** |

Красные — ровно те же, что были у `67ff463c`/`534ac7dd`: 4 паритетных
(`test_tool_phase_*`, `test_l2_on_*` — структурный `<Speech_Base>`), остальные
33 — предсуществующие в неfrozenset-файлах (t5150-миграции, fallback-recompose
стабы, webapp/outgoing, samples several). Новых падений не добавлено; 3 теста
лестницы миграций обновлены под новый шаг (`P0CINT`), не ослаблены.

## 10. Живой прогон `fe1e514a` (второй сэмпл) — R3: tone≠act и пустой RAG

Источник — `probes_final5-rerun.md` (кандидат `fe1e514a`, 7 прогонов, `invalid`
пусто). Зелёные: мета 0/9, Core 3294, FREQ, payload 1×1/0×0, closing 1×, case C,
завершение стенда. Красные два пункта: L1 B = `disagreement` (A/B → research 1/2)
и `rag.block_chars=0` в 4/5 при непустых фактах (`service_empty`).

### 10.1 A. L1 — `response_act` путался с тональностью

**Диагноз.** Запрос B начинается грубой претензией боту и лишь затем просит
разобрать чужие сообщения. Канон редакции 3 уже запрещал `hostile_rebuff/
banter/disagreement` для разбора материала, но не разделял **сущность** и
**манеру**: модель выбирала `response_act=disagreement` (человек спорит с ботом)
+ `tone=annoyed`, то есть трактовала `response_act` как классификацию входящей
реплики, а не как собственное действие по существу просьбы. Правила про
«оценку человека» в каноне нет с редакции 2 — конфликта правил не было, был
концептуальный пробел в определении поля.

**Исправление (редакция 4 канона, без списков фраз запроса):**
* `response_act` — «то, что ты ДЕЛАЕШЬ по существу просьбы», `tone` — манера;
  грубость/оскорбление/спор/провокация «меняют ТОЛЬКО tone… но никогда не
  меняют response_act»;
* приоритет внутри правила: тон → материал → оценка; «Материал важнее оценки:
  если в конце добавлен вопрос-оценка, сперва разбор, а оценка — его вывод»;
* `disagreement/hostile_rebuff/banter` — только когда «материала для разбора в
  просьбе нет: это ответ на выпад или спор, а не способ разобрать чужое
  поведение».

**Ступени/пины:** `PREV_DIRECT_L1_PLANNER_P0CINTR2` = ровно байты предыдущего
кандидата (9391/`ca1ba3049991`), `PREV_..._P0CINT` (9288/`23aae0c9499d`)
сохранён; активный канон **9750/`422e9d73d316`**; `PROMPT_MIGRATIONS` и
`ROLLBACK_MIGRATIONS` получили новый шаг (7 ступеней); `FACTORY_SET_SHA256_12`
`50492308595e` → **`3d82f756dd5a`** (метка `l1-planner-tone-separation`).
`test_prompt_migrations` — 43 passed.

**Синтетические кейсы** (`tests/test_speech_p0_l1_canonical.py`, 32 проверки):

```
rule7: tone-раздел раньше материала, материал раньше оценки (индексы)
case B  (research)              → mode serious, analysis 1×1, «как разбирать:»
        + tone=annoyed в том же плане НЕ меняет response_act
«ты мудак» без материала        → hostile_rebuff/emotional_reply/other: анализа нет;
        action=react → анализа нет
материал + вопрос-оценка        → research/analysis/разбор → research, анализ есть
```

Стенд печатает `l1_act_raw` / `l1_act_normalized` / `l1_act_rewritten`, поэтому
следующий raw покажет, был ли это выбор модели или работа таблицы синонимов.

### 10.2 B. RAG — «пусто» объяснено и разделено на сбой/отбраковку

**Диагноз (по коду + данным прогона).** После self-фильтра и дедупа остаются
3/7/8 фактов; дальше единственный шаг, способный обнулить набор, — LLM-реранк
(`flags.chat_rag_rerank_enabled=True`, typed-ветка A05). Точная причина пустоты
не была видна, потому что в raw не было ни счётчиков, ни статуса. Плюс найден
реальный дефект: `parse_rerank_selected("")` возвращал `empty` («валидный пустой
выбор»), поэтому **пустой ответ провайдера** молча обнулял RAG-блок и выглядел
как осознанное решение модели (`probes_final5-rerun` §8).

**Исправление:**
* `parse_rerank_selected`: пустой/blank ответ и `None` → новый статус
  `empty_response`; явные `{"selected":[]}` / `[]` остаются `empty` (A05).
* `_typed_rerank_apply`: `empty_response` → детерминированный bounded
  pre-rerank-fallback (`fallback_top_k`), событие `reranker/failed`,
  `reason_code=rerank_empty_response`, `fallback=true`. За «релевантный
  результат» это не выдаётся: пометка едет в raw.
* Наблюдаемость: каждый исход пишется в `_RERANK_LAST` (counts, status,
  response_format, fallback, latency, provider/model), включая legacy-ветку
  (`legacy_ok`/`legacy_empty_failopen`) — раньше успешный typed-OFF вызов
  оставлял снимок от предыдущего запроса.
* Стенд: `_RecordingMemory.rerank_rag_facts` фиксирует `candidates/selected/
  status/response_format/fallback/latency/model`; `_rag_service_diagnostics`
  ставит `rag_empty_reason`:
  `rerank_rejected` (явный пустой выбор → `rag_empty_is_correct=true`),
  `rerank_failed_empty` (сбой+fallback, но пусто → `false`), `service_empty`
  (причина не установлена). `rerank_fallback=true` виден и при непустом блоке.
* `self_check`/инварианты не менялись; self-echo и provenance-фильтры не
  тронуты.

**Тесты:** `tests/test_speech_p0_rerank_contract.py` (8):
`{"selected":[]}` → `[]` + `status=empty/fallback=false`;
`""`/`"   "`/`"\n"` → fallback=все факты + `status=empty_response/fallback=true`;
prose → `invalid`; валидный выбор → порядок оценки; ошибка провайдера →
fallback; парсер различает blank и явный пустой; fallback остаётся bounded.
`tests/test_speech_p0_rag_diag.py` (8): `rerank_rejected` (correct=true, счётчики
3→0), fallback-пометка при непустом блоке, `rerank_failed_empty` (correct=false).
Обновлены ожидания `test_rerank_contract_asap32.py` и
`test_graphrag_memory.py`: blank больше не «валидный пустой».

**End-to-end проверка через РЕАЛЬНЫЙ код продукта** (реальный
`MemoryManager.rerank_rag_facts` + подменённый только LLM-ответ):

```
провайдер вернул ""               → block 212 симв., 3 факта из fallback,
                                    rerank.status=empty_response, fallback=true,
                                    rerank_fallback=true, rag_empty_reason=нет
провайдер вернул {"selected": []} → block 0, rerank.status=empty,
                                    rerank.selected=0, fallback=false,
                                    response_format=json,
                                    rag_empty_reason=rerank_rejected,
                                    rag_empty_is_correct=true
```

То есть сбой больше не выглядит как отбраковка, а отбраковка не выглядит как
сбой — и обе видны в raw по счётчикам.

### 10.3 Тесты: delta против `fe1e514a`

| Набор | `fe1e514a` (до R3) | этот кандидат |
|---|---|---|
| `tests -k "speech_p0 or direct_l1 or prompt or composer or rerank or graphrag"` | 4 failed, 1172 passed (те же 4) | **4 failed, 1172 passed** |
| `test_prompt_migrations` | 43 passed | **43 passed** |
| новые/обновлённые целевые файлы | — | l1_canonical 32, rerank_contract 8, rag_diag 8, meta_closing 4, detector 5, guard 4 |
| `--self-check` | PASS 40/40 | **PASS 40/40** |

### 10.4 Полный прогон (без UI-e2e): delta против `fe1e514a`

```
fe1e514a : 37 failed, 15749 passed, 1 skipped, 7 errors  (13:22)
candidate: 38 failed, 15768 passed, 1 skipped, 7 errors  (13:42)
```

Все 37 прежних падений присутствуют и не изменились (4 паритетных
`test_tool_phase_*`/`test_l2_on_*` + 33 предсуществующих в посторонних файлах:
t5150-миграции, fallback-recompose-стабы, webapp/outgoing, samples, registry,
summary-*). Добавилось ровно одно имя:

```
tests/test_asap8_initreply_binding.py::test_case6b_invalid_reaction_is_honest_silence
```

Оно **не связано с R3** и является order-flaky в этом окружении:
* изолированно — `1 passed`; весь модуль — `14 passed`;
* в паре `test_asap7_direct_settings.py + test_asap8_initreply_binding.py`
  модуль падает и на кандидате, и на `fe1e514a`, причём **разными** тестами
  (`case6b` здесь, `case4_transport_never_picks_addressee` на `fe1e514a`);
  в логе перед этим — `random_source reserve read failed` и
  `database_connection_unrecoverable` от предыдущего файла;
* мой diff не касается react/reply-binding путей (только канон L1, миграции,
  реестр, реранк RAG и стенд).

Итог: новых падений, вызванных изменениями, нет; 7 `errors` — те же teardown-
ошибки предсуществующих файлов, что и в прогоне `fe1e514a`.

## 11. Что осталось (честные пробелы)

1. **Повторный живой прогон A/B/C + forced** на этом кандидате: он один
   закрывает выбор L1 (research 2/2 или честная недетерминированность),
   мету 0/8 с новым хвостом user-части и причину пустого RAG из `rows_detail`.
   Локально нет `.env`/БД.
2. В raw следующего прогона должны остаться `pins.harness.sha256`,
   `l2_meta.analyzer_sha256`, `l1_act_raw`/`l1_act_normalized`,
   `rag.rows_detail`/`rag_empty_reason`.
3. Правка продукта в этой полосе — только по §3 (позиция требования в
   user-части) и канон L1; фильтры self-echo и длины не менялись.
4. F1 ревью (live-подтверждение) и F7 (карта/гейт) — не моя зона:
   F1 закрывается тем же живым прогоном, F7 — PM/Orchestrator.
