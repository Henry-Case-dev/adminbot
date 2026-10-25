# P0 SPEECH — интеграция исправлений ревью (F2–F6)

- **LANE:** `SPEECH-INT-FIX`, один писатель, worktree `C:\Code\Python\adminbot-wt-speech-int`,
  ветка `task/p0c-int`.
- **Кандидат:** `e0a46414` + фикс стенда ниже (merge `505c0422` + F2/F4/F5/F6;
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

## 9. Что осталось (честные пробелы)

1. **Живой прогон A/B/C на сервере** тем же harness (`--case A/B/C`,
   `--rag-source service`) — разблокирован этим фиксом и остаётся за DevOps:
   закрывает 0/8 меты на кандидате, case C (короткий ответ без обрезания),
   RAG-блоки A≠B из реального retrieval, `core.chars=3294` в отчёте.
   Локально нет `.env`/БД, поэтому сам прогон здесь невыполним.
2. В raw живого прогона должны остаться `pins.harness.sha256` (файл стенда) и
   `l2_meta.analyzer_sha256` (детектор) — именно это закрывает претензию
   «исполнялся не тот harness»; снять их нужно на сервере, здесь их взять неоткуда.
3. Правки продукта в этой полосе не делались: только стенд, анализатор,
   фикстура и тесты. Поведение бота не менялось.
4. F1 ревью (live-подтверждение no-meta) и F7 (карта/гейт) — не моя зона:
   F1 закрывается тем же живым прогоном, F7 — PM/Orchestrator.
