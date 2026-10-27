# P0C-INT R3b — повторный живой прогон `fe1e514a` (второй сэмпл, без деплоя)

**Вердикт: `FAILED` по живым критериям; деплой не начинался (прод остаётся `534ac7dd`).**
Матрица исполнена целиком: 7/7 прогонов `exit=0`, `invalid` пусто, один ssh-логин, процессов после
не осталось. Подтверждены Core, FREQ, payload 1×1/0×0, closing 1×, мета 0/8, case C и фикс
завершения стенда. Два критерия не выполнены: **L1 natural A/B = `research` 1/2** (B →
`disagreement`; в первом сэмпле было 2/2) и **`rag.block_chars > 0`** (пусто в 4/5 — та же
`service_empty`, что и в первом сэмпле, причина — валидный пустой выбор LLM-реранкера).

Файлы этого сэмпла: `probes_final5/rerun_b/` (raw, stdout/stderr, stage_sha, selfcheck, sha-листы).
Первый сэмпл остаётся как есть: `probes_final5.md` + файлы в `probes_final5/` (коммит `e72be00a`).

## 1. Привязка

| Проверка | Значение |
|---|---|
| кандидат / tree | `fe1e514ae37dd2c07c1b833a4c3b8489c20a1215` / `ae40da53b0e0` |
| worktree HEAD | `4bf1b36a3306…`, tree `f716e233f011…` = кандидат + docs-коммит (diff: только `int-fix.md`, +3/−2) |
| стейджинг | `git archive fe1e514a` (`*.py`, `config/`, `info_text.md`, `tools/`, `probes_full/`) → `/tmp/p0c-int3`; `.env` и `local_database.db` — симлинки на `/var/www/admin_bot`; python 3.12.3 (venv прода) |
| tgz sha256 (локально = на сервере) | `ac1991d88413a5aedb1835c4ddc34058648bc55fcad3f66c14f632e91d5e585e` (11 273 889 B) — совпал с первым сэмплом |
| harness / analyzer sha256 на сервере | `a750a98368a7cbad…` / `de9783ce2f685d23…` — совпали с локальными |
| модули (`direct_chat_service`, `direct_l1`, `chat_prompts`, `prompt_style_blocks`) | `bc9e0b16f9cd…`, `1d4abb7b7380…`, `a444c89a7452…`, `982352b2dd58…` — совпали с worktree кандидата (`sha_local.txt`) |
| self-check на сервере | **PASS 40/40**, `code_l1_canon 9391/ca1ba3049991`, guard UnboundLocal чист |
| `--ast-check` | `findings=0`, exit 0 |
| пины git в raw | `ERR:…rev-parse`, `dirty=true` — в стейджинге нет `.git`; привязка на `stage_sha.txt` + sha модулей |

Замечание к формулировке полосы: «tree `4bf1b36a`» — это не tree кандидата, а **docs-коммит**
`4bf1b36a3306…` поверх него (его tree `f716e233f011…`); tree самого `fe1e514a` — `ae40da53b0e0`.

## 2. Соединения и время

| # | Время (UTC) | Что | Итог |
|---|---|---|---|
| 1 | 11:56:33–12:01:14 | SFTP (tgz + скрипт) → один bash-скрипт: self-check → 7 прогонов (`timeout 300`) → postcheck → выгрузка 23 файлов | **успех**, 340.7 с, сессия закрыта |

Один логин, ни одной неудачной аутентификации, ретраев нет. `timeout 300` не сработал ни разу:
прогоны заняли 24–39 с и завершились сами (`exit_after_summary`-фикс кандидата работает),
`MATRIX_DONE` записан. После сеанса процессов стенда нет (`pgrep` даёт только self-match оболочки).

## 3. Матрица

Команда кандидата: `--root /tmp/p0c-int3 --rag-source service --use-code-l1-canon`;
baseline: `--root /var/www/admin_bot --rag-source service`.

| Прогон | L1 | act raw → norm | mode | канон | попыток | `invalid` | `rag_source` | block_chars | L2 симв. | мета |
|---|---|---|---|---|---|---|---|---|---|---|
| `newA` | llm | `research` → `research` | **serious** | code `ca1ba3049991` | 1 | — | service | 0 | 449, 362 | 0/2 |
| `newB` | llm | **`disagreement`** → `disagreement` | **casual** | code `ca1ba3049991` | 1 | — | service | 0 | 155, 242 | 0/2 |
| `newC` | llm | `answer` → `answer` | casual | code `ca1ba3049991` | 1 | — | service | 0 | 184 | 0/1 |
| `new_forced_A` | forced | — | serious | code `ca1ba3049991` | — | — | service | 0 | 387, 328 | 0/2 |
| `new_forced_B` | forced | — | serious | code `ca1ba3049991` | — | — | service | **146** | 533, 481 | 0/2 |
| `oldA` | llm | `answer` → `answer` | casual | PG `6c2ddc17c998` | 1 | — | service | 146 | 475, 292 | 0/2 |
| `oldB` | llm | `analysis` → `analysis` | casual | PG `6c2ddc17c998` | 1 | — | service | 146 | 754, 350 | 2/2 |

- `stage_errors` пуст; `l2_chars` 155–754 при `max_tokens=2400` (обрезания нет), L2 `deepseek-v4-flash`
  @ `nano-gpt.com`; PG `read_only=on`, SQLite `mode=ro`; окно 64/66 сообщений, `settings_keys=537`,
  `chat_params=6`, `graph_facts_rows=40`.
- L1-канон кода `9391/ca1ba3049991`, PG `8261/6c2ddc17c998` (`pg_matches_code=false`) — флаг
  `--use-code-l1-canon` обязателен, у baseline каноны совпадают.

## 4. Критерий 1 — L1 natural A/B

A: `research`, `serious`, conf 0.75, 1 попытка — как и в первом сэмпле.
B: `disagreement`, `casual`, `tone=annoyed`, conf 0.95, `target_user_id=Макс`, 1 попытка.
`l1_act_rewritten=false` в обоих → это выбор модели по канону, а не работа alias-таблицы.

| Сэмпл | A | B |
|---|---|---|
| A (коммит `e72be00a`) | `research` | `research` |
| B (этот прогон) | `research` | **`disagreement`** |

**Агрегат: A 2/2 `research`, B 1/2.** Текст B начинается с прямой претензии к боту
(«Ты какауюто хуйню пизданул брат, давай по другому вопрос…») и лишь затем просит разобрать
сообщения Ринтаро; канон `ca1ba3049991` содержит и правило «просьба разобрать материал не является
выпадом», и словарь враждебных актов — на этом входе модель выбирает то одно, то другое при
`temperature=0.7` и одной попытке. Требование «2/2» на одном сэмпле выполнялось, на двух — нет.

## 5. Критерий 2 — мета 0/8

0/9 с case C (0/8 без неё) — как в первом сэмпле. Анализатор `de9783ce…`, его sha в каждом raw
(`l2_meta.analyzer_sha256`). Независимый прогон `analyze_l2_meta.py --glob raw_*.json` по этим 7 raw:
кандидат 0/9, по всем 13 ответам двух наборов — 2/13 (оба флага у легаси-базы).

Все 9 ответов кандидата начинаются с сути: «Бля, ну ты не злобный…», «Да не, не злобный…»,
«Да норм, под дождём приятно…», «Злобный — не то слово…», «Да хуй его знает, Макс. Ринтаро…».

## 6. Критерий 3/5 — Core и FREQ

| Прогон | Core chars / sha12 / in_system | system chars | FREQ |
|---|---|---|---|
| 5 прогонов кандидата | **3294 / `ead77b2ab509` / true** | 14409 / 14377 / 14406 | **true** (`occasional=false`, `off=false`) |
| `oldA` / `oldB` | 2507 / `e62de1fcd7a2` / true | 13863 / 13895 | true |

FREQ приходит из живого конфига PG, не из few-shot. Слои: core 3294, identity 5048, expression 1069,
base_prompt 3081.

## 7. Критерий 6 — payload

| Прогон | директива / writer / no_meta | `no_meta_contract` | closing | инварианты |
|---|---|---|---|---|
| `newA`, `new_forced_A`, `new_forced_B` | **1 / 1 / 1** | applies, count 1, required 1, carrier `plan_block` | 1 | `invariant_1x1`, `invariant_no_meta_1x1`, `invariant_closing_1x1` — true |
| `newB`, `newC` | **0 / 0 / 1** | то же | 1 | `invariant_0x0=true` |
| `oldA`, `oldB` | 0 / 0 / 0 | `applies=false` (в легаси-дереве константы нет) | 0 | — |

Положение closing проверено по фактическому payload, не только по счётчику: `</Current_Question>` →
закрывающий блок → конец user-части (после него ничего), в system 0 вхождений, ровно 1 в user.
`invalid` пуст 7/7.

## 8. Критерий 4 — RAG

| Прогон | rows | ids (первые) | rows_sha12 | self→dedup | origins в 10 строках | block |
|---|---|---|---|---|---|---|
| `newA` / `new_forced_A` | 10 | 20479, 20476, 21254, 19433… | `69c975230b9d` | 3 → 3 | `derived_belief` 2, `bot_direct_reply` 7, `chat_history` 1 | **0** |
| `newB` / `new_forced_B` | 10 | 20482, 20263, 19636, 16816… | `3ab839c6f464` | 7 → 7 | `derived_belief` 4, `bot_direct_reply` 3, `chat_history` 3 | A: **0**, B-forced: **146** |
| `newC` | 10 | 20957, 18067, 16648… | `f7ca6fdde775` | 8 → 8 | `chat_history` 7, `voice_transcript` 1, `bot_self_reply` 2 | **0** |
| `oldA` / `oldB` | 10 (tuple) | — | — | 0 → 0 (диагностика к легаси-контракту неприменима) | — | 146 / 146 (`2bd623967c59`) |

`rag_source=service` 7/7; наборы A и B разные, query доходит до retrieval, self-echo-строки
отброшены продуктовым предикатом. `rows_detail` с origin'ами пишется — причина пустого блока
теперь видна машинно.

**Почему пусто.** После self-фильтра и дедупа остаются 3 / 7 / 8 / 3 факта, т.е. `all_self_origin`
нет; ставится `rag_empty_reason=service_empty`, `rag_empty_is_correct=false`. Дальше в продуктовом
коде только: LLM-реранк (`rerank_rag_facts`, typed-ветка `MCA_TYPED_RERANKER_ENABLED` по умолчанию
ON, валидный пустой выбор → `[]` → пустой блок, A05), граф-активация (только добавляет), хинт
«золотых» (отдельный возврат), затем детерминированные `_mark_rag_fact` + `build_rag_context`.
Реранк — единственный шаг, способный обнулить непустой набор.

Подтверждение данными: при **идентичных** строках и отборе (B natural vs B forced:
`rows_sha12=3ab839c6f464`, 7→7) в этом сэмпле один прогон дал 146 символов, другой 0; в первом
сэмпле наоборот — `newC` (8→8) дал 951, а `new_forced_B` — 0. Варьируется именно реранкер.

**Критерий `block_chars > 0` не выполнен** (0 в 4/5, 8 из 10 по двум сэмплам), но это не self-echo и
не баг фильтра: причина названа, решение (переформулировать критерий под A05 или требовать
инструментирования реранка) — за Reviewer/Builder. Ослаблять критерий по факту нельзя.

**Ограничение стенда:** в read-only профиле не загружено расширение `sqlite-vec`, поэтому во всех
прогонах (и baseline) в stderr `graphrag RAG: KNN failed — FTS fallback | no such module: vec0`.
Retrieval — реальный продуктовый код, но по FTS-ветке; KNN-ветку прода эта матрица не воспроизводит.

## 9. Критерий 7 — case C

`newC`: L1 сам выбрал `answer` / `compact` / `chat`, mode `casual`, 1 L2-вызов (184 симв.):
«Да норм, под дождём приятно тупить в окно или идти под зонтом, когда никуда не надо…».
`question_source=synthetic_case_c`, окно и точка времени — как у A (64 сообщения), вопрос A из окна
исключён; режим не навязан. Первый сэмпл: `answer/casual`, 218 симв.

## 10. Безопасность (до/после)

| Параметр | До (11:56:34Z) | После (12:01:14Z) |
|---|---|---|
| unit `admin_bot` | active, `NRestarts=0`, `ActiveEnter=2026-10-24 21:03:19 UTC` | то же |
| healthz `https://127.0.0.1` / `http://127.0.0.1` | 000 / 308 | 000 / 308 |
| git HEAD / dirty | `534ac7dd` / 13 | `534ac7dd` / **13** |
| `local_database.db` size / mtime | 1 626 017 792 / 11:54:36.441 | **то же** |
| `…db-wal` / `…db-shm` | 4 223 032 / 32 768 | 4 223 032 / 32 768 (mtime 12:01:00 — пишет сам бот) |
| процессов стенда после | — | 0 (7/7 `exit=0`, `MATRIX_DONE`) |

Записей, рестартов, checkout не было. В stderr только ожидаемые read-only предупреждения
(`embedding cache lookup/store failed`, `graphrag RAG: touch failed`), они внутри продуктовых
try/except. Стейджинг `/tmp/p0c-int3` оставлен как артефакт прогона (`/tmp` 3.6 → 3.5 GB свободно),
процессов нет.

## 11. Приёмка

| Критерий | Факт (этот сэмпл) | Агрегат двух сэмплов | Статус |
|---|---|---|---|
| L1 natural A/B → research 2/2 | A `research`, B `disagreement` | A 2/2, B 1/2 | **FAIL** |
| мета 0/8 | 0/9 (0/8 без C) | 0/18 | **PASS** |
| Core 3294 / `ead77b2ab509` / in_system | 5/5 | 10/10 | **PASS** |
| `rag_source=service` + `rows_detail`/причина | 7/7, причина пишется | 14/14 | **PASS** |
| Пустой блок законен (`all_self_origin`/`no_facts`, `correct=true`) | `service_empty`, `correct=false` | то же | **FAIL (объяснён)** |
| FREQ из живого конфига | true 7/7 | 14/14 | **PASS** |
| payload 1×1 research / 0×0 answer | 1/1 ×3, 0/0 ×2 | совпадает | **PASS** |
| closing 1× после `</Current_Question>` | 1×, последним, system 0 | совпадает | **PASS** |
| `invalid` пуст | 7/7 | 14/14 | **PASS** |
| case C без навязанного режима | `answer/casual`, 184 симв. | то же | **PASS** |
| безопасность | без изменений | — | **PASS** |

## 12. Что дальше

1. **Builder** — L1 B: канон должен либо явно отдавать приоритет «разбор материала» над реакцией
   на выпад в адрес бота, либо требование «research 2/2» в ledger честно ослабляется до «A 2/2,
   B ≥ 1/2» с обоснованием. Сейчас один и тот же канон даёт `research` и `disagreement` на одном входе.
2. **Builder/Reviewer** — RAG: причина пустого блока установлена (typed-реранк, A05), но не
   инструментирована в raw (`candidate_count/selected_count/status`). Минимальная правка стенда —
   писать исход реранка; решение по критерию `block_chars>0` — за Reviewer.
3. **DevOps** — в следующем прогоне поднять `sqlite-vec` в read-only профиль (или писать
   `vec_knn=false`), чтобы KNN-ветка не подменялась FTS молча.
4. Деплой `fe1e514a` не начинать: живые критерии не зелёные; прод остаётся `534ac7dd` (2.58.130).

## 13. Файлы

`probes_final5/rerun_b/`: `raw_*.json` (7), `*.out`/`*.err` (7+7), `exits.txt`, `MATRIX_DONE`,
`stage_sha.txt`, `selfcheck.out/.err`, `astcheck.out`, `run.log`, `precheck.txt`, `postcheck.txt`,
`table_r3.txt`, `analysis.json`, `sha_local.txt`, `local_meta.json`, `sha256.txt`, `README.md`.
Скрипты прогона: `OPENCODE_WORKFLOW_SCRATCH/p0c-int3/` (`run_int3.py`, `p0c-int3_run.sh`,
`analyze_int3.py`, `console.log`).
