# P0-CORRECTIVE — стенд: `--case C` (короткая бытовая реплика) и фикс F6

- **LANE:** `P0C-META-FIX` (после корректировки scope — только стенд).
- **Worktree:** `C:\Code\Python\adminbot-wt-speech-meta`, ветка `task/p0c-meta`.
- **База кандидата:** `b7201033` (содержит alias `f42e2257` + Core/L1 `0428c271`).
- **Продуктовый код, промпты и продуктовые тесты — НЕ изменялись.** К началу
  работы рабочее дерево было чистым (`git status --short` пуст), поэтому
  откатывать было нечего: правок в `services/prompt_style_blocks.py`,
  `services/direct_l1.py`, `services/prompt_composer.py`,
  `services/chat_prompts.py` и продуктовых тестах Writer'а этот lane не делал
  ни до, ни после корректировки. Контракт Writer по мета-вступлениям ведёт
  другой исполнитель в другой рабочей копии.
- **Изменён один файл кода** (+ это evidence): `probes_full/harness_probe_full.py`
  (sha256 `57d89884d5ed80bc92a95ab566211949d4ae3df01b8c2ee91cb10bf519ed0cfb`,
  46255 символов).

## 1. Что сделано и чего не сделано

Сделано:

1. `--case C` — короткая бытовая реплика через тот же реальный пайплайн
   (L1 → режим/предикат → payload → L2), без навязывания режима.
2. F6: `manifest.versions.core` больше не отдаёт 0 — отчёт о core берётся из
   реально отрендеренного слоя.
3. Инвариант payload по контракту «без мета-вступления»: 1 раз на разборе,
   0 раз на обычном ответе. Разрыв помечается `invalid`, а не зелёным прогоном.
4. Self-check расширен офлайн-проверками нового кода (без PG/LLM).

Не сделано (осознанно):

- Live-прогон C/A не выполнялся: в этой рабочей копии нет `.env` с
  кредами LLM и нет `local_database.db` (файлы не в git). Требуется серверный
  прогон — команды в §7.
- Продуктовые промпты не тронуты: правка контракта Writer — чужой scope.

## 2. `--case C`: что именно прогоняется

`CASE_C_QUESTION` (константа стенда, одна строка, 57 симв.):

```
Слушай, а ты дождь любишь или тебя от него тоже ломает?
```

Почему так, а не «взять случайное сообщение из БД»:

- это обычная бытовая реплика-вопрос, а не просьба разбирать историю/переписку
  (проверка 8 §5 ТЗ — «обычный вопрос — коротко»);
- **то же историческое окно и та же точка времени, что у A** (`window_A`,
  `TS_A = 1792873281`), сообщение запроса A (`tg 1175252`) из истории
  исключено — как и раньше. Отличается РОВНО текущая реплика: любая разница
  в режиме/длине ответа объясняется ею, а не другим контекстом;
- текст синтетический, поэтому происхождение пишется честно:
  `question_source = "synthetic_case_c"` + `question_note`. У A/B остаётся
  `question_source = "db"` (реальное сообщение окна) — их вход, порядок блоков
  и payload не менялись.

Маршрут L1 не навязывается. Если L1 отправит C в `research`, это будет
записано как есть (`mode`, `analysis_predicate`, `l1_plan`) и является
находкой, а не сбоем стенда. `--force-plan research` для C использовать
нельзя: это диагностический форс, он помечается `forced=true` и к проверке 8
не относится.

По умолчанию `--case C` делает **1 L2-вызов** (`--repeats` не задан → 1;
у A/B прежние 2). Явный `--repeats` перекрывает это.

## 3. F6: почему стенд показывал `core = 0`

`manifest.versions` — это `Mapping[str, str]`, где `versions["core"]` —
**ревизия** (строка вида `act:…`), а не текст. Прежняя строка стенда:

```python
len(getattr(manifest.versions, "core", "") or "")   # у dict нет атрибута → 0
```

читала mapping как объект с атрибутом, поэтому всегда получала `""` → `0`,
хотя реальный слой `core` в system был (в прогоне `probes_final2` — 3294
симв., sha12 `ead77b2ab509`).

Теперь `core_report(manifest, system)`:

- `chars` — из `layers[block_id="core"].chars` (реально отрендеренный слой);
- `revision` / `detail` — из `versions["core"]` / `versions["core_detail"]`;
- `sha12`, `text_chars` — по фактическому тексту слоя;
- `in_system` — этот самый текст физически входит в финальный system
  (после scrub), т.е. отчёт нельзя подменить слоем, который не доехал.

Продукт не менялся: это только отчётность стенда.

## 4. Новый инвариант payload (§3 ТЗ)

Прежние счётчики проверяли только `ANALYSIS_DIRECTIVE_TEXT` /
`ANALYSIS_WRITER_TEXT`. Контракт «без мета-вступления» (`psb.NO_META_STRUCTURE_TEXT`)
не проверялся вообще, поэтому перенос/потеря этого текста в сборке прошёл бы
незамеченным. Добавлено:

- `payload_counts` считает `no_meta` в system/user/total;
- в `_run`: `no_meta_contract = {applies, count, required}`;
  `required = 1`, если директива обязана ехать в plan-блоке
  (`include_analysis`) ИЛИ в режимном блоке `deep_research`
  (когда extent-блок его не заменил), иначе `0`;
- расхождение → `invalid = "no_meta_invariant"` (прогон не считается PASS и
  L2 не вызывается);
- на legacy-дереве без константы (прод до фикса) инвариант не применяется,
  но это видно в отчёте (`applies: false`), а не замалчивается.

Практический смысл: если контракт Writer переедет в хвост user-части внутри
`_l2_write_answer`, стенд обязан этот блок отразить. Сейчас он этого не
делает (см. §8) — и тогда прогон честно упадёт в `invalid`, а не покажет
ложный PASS.

## 5. Self-check (реальный вывод, 20/20 PASS)

`py -3 probes_full/harness_probe_full.py --self-check` → `EXIT=0`,
`"self_check": "PASS"`:

| Проверка | Результат |
|---|---|
| `counts_1x1`, `ascii_marker_zero`, `payload_1x1` | true |
| `predicate_research`, `predicate_answer`, `mode_research_serious` | true |
| `modules_under_root`, `code_l1_canon_material_routing`, `code_l1_canon_not_pg_stage` | true |
| `core_full_not_truncated` | true |
| `no_meta_directive_1x1_research`, `no_meta_directive_0_answer` | true |
| `core_report_chars`, `core_report_revision`, `core_report_in_system`, `core_report_sha12` | true |
| `case_a_unchanged`, `case_c_synthetic`, `case_c_same_window_as_a`, `case_c_short_single_line` | true |

Фактические числа (из того же вывода):

```json
"synthetic_payload": {"total": {"directive": 1, "writer": 1, "no_meta": 1},
                      "invariant_1x1": true, "invariant_no_meta_1x1": true}
"answer_payload":    {"total": {"directive": 0, "writer": 0, "no_meta": 0},
                      "invariant_0x0": true, "invariant_no_meta_0": true}
"core_report": {"revision": "abc123def456", "detail": "full:owner_setting",
                "chars": 53, "rendered": true, "sha12": "cbc484f32fe8",
                "text_chars": 53, "in_system": true}
"code_l1_canon": {"chars": 9288, "sha12": "23aae0c9499d",
                  "prev_p0cs2_sha12": "f6f5d3b1fc1d"}
"pins.git": {"commit": "HEAD ветки task/p0c-meta", "branch": "task/p0c-meta",
             "dirty": false, "dirty_files": []}
```

Self-check повторён на уже закоммиченном чистом дереве (`dirty=false`, HEAD
ветки `task/p0c-meta`) — тот же `PASS` 20/20 и тот же sha стенда
`57d89884d5ed80bc92a95ab566211949d4ae3df01b8c2ee91cb10bf519ed0cfb`.

`core_report` в self-check собран на синтетическом манифесте
(`PromptManifest` + `LayerTrace(block_id="core", text=…)`): проверяется сама
отчётная функция, включая регрессию F6 (`chars != 0`, ревизия из `versions`,
`in_system`).

## 6. Офлайн-матрица инварианта (реальные значения продукта)

Чтобы инвариант не был ложным, прогнаны все носители директивы
(`plan-блок` / режимный блок `deep_research` / extent-блок):

```
research/auto        mode=serious       extent_block=False include_analysis=True  no_meta=1 required=1 OK
research/detailed    mode=deep_research extent_block=True  include_analysis=True  no_meta=1 required=1 OK
answer/compact       mode=casual        extent_block=True  include_analysis=False no_meta=0 required=0 OK
research/''/report   mode=deep_research extent_block=False include_analysis=False no_meta=1 required=1 OK
research/auto/report mode=deep_research extent_block=False include_analysis=False no_meta=1 required=1 OK
research/normal/report mode=deep_research extent_block=True include_analysis=True no_meta=1 required=1 OK
```

Последние три строки — тот самый угол, где директива едет режимным блоком
(`include_analysis=False`, extent пуст): без условия `response_mode ==
"deep_research"` инвариант дал бы ложный `invalid`.

## 7. Что осталось: live-прогон обязателен (локально невозможен)

В этой копии нет `.env` и `local_database.db` — прогон падает на загрузке PG
(`fatal: FileNotFoundError … .env`), LLM не вызывается. Команды для серверного
сеанса (staging того же коммита, read-only PG + SQLite `mode=ro`, как в
`probes_final2` §1):

```
py -3 probes_full/harness_probe_full.py --root . --case C --label p0-meta-C \
    --out probes_c/raw_case_C.json
py -3 probes_full/harness_probe_full.py --root . --case A --label p0-meta-A \
    --out probes_c/raw_case_A.json
py -3 probes_full/harness_probe_full.py --root . --case A --force-plan research \
    --label p0-meta-forced-A --out probes_c/raw_forced_A.json
```

Что читать в отчёте:

- `mode` / `analysis_predicate` / `l1_plan.response_act` — куда L1 отправил C
  (навязывания нет; `research` у бытовой реплики — находка);
- `no_meta_contract` — `count`/`required`; `invalid` не должен быть
  `no_meta_invariant`;
- `core.chars` / `core.revision` / `core.in_system` — F6 на живом манифесте
  (ожидается ~3294 и `full:owner_setting`, а не 0);
- `l2_texts[0]` — первая фраза ответа C (должна нести суть, а не анонс
  действия) и длина (обычная реплика — короткая, без обрезания);
- `payload_counts` — A/forced-A: `1×1` по analysis-текстам и `no_meta=1`.

## 8. Ограничение стенда (известное, не замалчивается)

Стенд собирает user-часть сам, повторяя порядок сервиса
(`time_line → plan → speech/lessons при composer OFF → user_blocks → evidence`)
в `_run`. Если правка контракта Writer добавит финальный блок в хвост
user-части внутри `_l2_write_answer`, стенд этот блок не увидит и пометит
прогон `invalid = "no_meta_invariant"` (а не покажет PASS). Тогда в стенд
нужно добавить ровно этот блок — сразу после
`parts.extend(("<Target_User>…", "<Current_Question>…"))` в `_run`,
до `user_text = "\n\n".join(...)`. Позицию и текст задаёт продуктовый код;
стенд не изобретает ни текста, ни порядка.

## 9. Проверки дерева (read-only, продуктовый код не менялся)

```
py -3 -m py_compile probes_full/harness_probe_full.py     → EXIT=0
py -3 probes_full/harness_probe_full.py --self-check      → EXIT=0, PASS (20/20)
py -3 -m pytest tests/test_prompt_migrations.py tests/test_p0_prompts_core.py -q
                                                           → 52 passed
py -3 -m pytest tests/test_speech_p0_core_serious.py tests/test_speech_p0_corrective_l1_route.py -q
                                                           → 22 passed
```

## 10. Итог

- Файл: `probes_full/harness_probe_full.py` (+173/−21 строк).
- A/B: вход, порядок блоков и payload не изменены; добавлены только поля
  отчёта (`question_source = "db"`, `sources.window_key`,
  `no_meta_contract`, новый формат `core`).
- Честные границы: live-C не выполнен (нужен серверный сеанс), F6 доказан
  офлайн на синтетическом манифесте, перенос Writer-контракта в хвост
  user-части потребует одной строки в стенде (§8).
