# P0C-INT R3 — живой прогон кандидата `fe1e514a` (read-only, без деплоя)

> **Обновление R3b (2026-10-25 12:01 UTC, второй независимый сэмпл).** Тот же кандидат и стенд
> прогнаны ещё раз (один логин, 7/7 `exit=0`, `invalid` пусто): Core 3294/`ead77b2ab509`, FREQ,
> payload 1×1/0×0, closing 1×, мета 0/9, case C и `rag_empty_reason=service_empty` повторились.
> **L1: A `research`, B `disagreement`** → по двум сэмплам `research` A 2/2, **B 1/2**, т.е. §4 ниже
> («research 2/2») — свойство одного сэмпла, а не устойчивый результат. RAG: пусто 4/5 (в этом
> сэмпле непустой `new_forced_B` 146 симв. вместо `newC` 951). Подробности и файлы —
> `probes_final5-rerun.md` и `probes_final5/rerun_b/`.

**Вердикт: FAILED (один пункт приёмки).** L1 natural A/B впервые дал `research/serious` 2/2,
мета-вступлений **0/8** (0/9 с case C), ядро/FREQ/payload/закрывающий блок — зелёные. Не выполнен
только RAG: у A/B/forced блок `<RAG_Memory>` по-прежнему пуст, причём **не** из-за self-origin —
кандидат сам пишет `rag_empty_reason=service_empty`, `rag_empty_is_correct=false`, а диагностика
показывает 3/7 живых фактов после self-фильтра и дедупа. Деплой не начинался (запрещён полосой).

- **Кандидат:** `fe1e514ae37dd2c07c1b833a4c3b8489c20a1215` (ветка `task/p0c-int`), worktree
  `C:\Code\Python\adminbot-wt-speech-int` на `4bf1b36a3306b60123e524d92311ecadf3877e4f`
  (docs-коммит поверх кандидата: diff — только `evidence/p0-hotfix/int-fix.md`, продуктовый код
  байт-в-байт).
- **База сравнения:** прод `534ac7dd` (2.58.130, `/var/www/admin_bot`), не изменялся.
- **Стенд:** `probes_full/harness_probe_full.py` sha256 `a750a98368a7cbad…` (staged),
  анализатор `probes_full/analyze_l2_meta.py` sha256 `de9783ce2f685d23…` (не менялся с R2).
- **Окно:** 2026-10-25 11:50–11:55 UTC (локально 23:50–23:55, UTC+12).

## 1. Привязка и стейджинг

Стейджинг собран `git archive fe1e514a` (`*.py`, `config/`, `info_text.md`, `probes_full/`,
`tools/`; без `.git`, `.env`, БД), 1521 запись, 1369 `.py`. Разложен в `/tmp/p0c-int3` (38 MB),
`.env` и `local_database.db` — симлинки на `/var/www/admin_bot`. Интерпретатор —
`/var/www/admin_bot/venv/bin/python` 3.12.3.

| Проверка | Значение |
|---|---|
| `stage_sha.txt` | `candidate=fe1e514a`, `tree_of=4bf1b36a` |
| tgz стенда | sha256 `ac1991d88413a5ae…`, 11 273 889 B (передан по SFTP) |
| harness sha256 (staged) | `a750a98368a7cbad9f0052b55ba2b9a39717edd1cdda8694a85f4ce2b008585e` |
| analyzer sha256 (staged) | `de9783ce2f685d23787d44a14b045f7d5d98c3d74677b854ff15503a957d43f8` |
| self-check на сервере | **PASS 40/40**, `code_l1_canon` **9391 / `ca1ba3049991`** (PG 8261/`6c2ddc17c998`, `pg_matches_code=false` → флаг `--use-code-l1-canon` обязателен) |
| `--ast-check` | `findings=0` |
| пины git в raw | `ERR…rev-parse`, `dirty=true` — в стейджинге нет `.git`; привязка на `stage_sha.txt` + sha модулей (как в R2) |

## 2. Соединения (fail2ban-дисциплина)

| # | Время (UTC) | Что | Итог |
|---|---|---|---|
| 1 | 11:50:12–11:54:45 | один логин (BatchMode-эквивалент, ConnectTimeout 20, без agent/keys) → SFTP tgz+скрипт → один скрипт (self-check, 7 прогонов, анализ, упаковка) → SFTP результата → очистка `/tmp` | **успех**, exit 0 |

Итого **1 логин**, неудачных аутентификаций и ретраев нет; дополнительный сеанс не понадобился
(стейджинг не падал). Upload 11.3 MB — 52 с, весь скрипт — 3.5 мин, download 0.11 MB — 2.8 с.
`/tmp/p0c-int3*` после сеанса: 0 файлов (staging и tgz удалены внутри скрипта).

## 3. Матрица прогонов

Команда кандидата: `--root /tmp/p0c-int3 --rag-source service --use-code-l1-canon`;
baseline: `--root /var/www/admin_bot --rag-source service` (без code-canon). L2 — `deepseek-v4-flash`
@ `nano-gpt.com`, `max_tokens=2400`, `temperature=0.7`, A/B по 2 ответа, C — 1.

| Прогон | L1 | act raw → norm | mode | canon | попыток | `invalid` | L2 симв. | мета |
|---|---|---|---|---|---|---|---|---|
| `newA` (natural) | llm | `research` → `research` | **serious** | code `ca1ba3049991` | 1 | — | 394, 656 | 0/2 |
| `newB` (natural) | llm | `research` → `research` | **serious** | code `ca1ba3049991` | 1 | — | 565, 398 | 0/2 |
| `newC` (natural) | llm | `answer` → `answer` | casual | code `ca1ba3049991` | 1 | — | 218 | 0/1 |
| `new_forced_A` | forced | — | serious | code `ca1ba3049991` | — | — | 230, 522 | 0/2 |
| `new_forced_B` | forced | — | serious | code `ca1ba3049991` | — | — | 356, 556 | 0/2 |
| `oldA` (baseline) | llm | `analysis` → `analysis` | casual | code `6c2ddc17c998` (PG) | 1 | — | 782, 407 | **1/2** |
| `oldB` (baseline) | llm | `clarification` → `clarification` | casual | code `6c2ddc17c998` (PG) | 1 | — | 266, 447 | 0/2 |

- Ни одного `invalid`/`fatal`/`stage_errors`; `l2_chars` непустые везде.
- **Exit-фикс кандидата подтверждён:** все 7 процессов завершились сами, `exit_after_summary=yes
  in 0s`, rc=0, длительность прогона 22–36 с (в R2 было 15 мин по `timeout`).
- PG-сессия `read_only=on`; SQLite `mode=ro`; окно A/B — 64 сообщения, `settings_keys=537`,
  `chat_params=6`, `graph_facts_rows=40`.
- L1 кэш-канон PG всё ещё старый (`pg_matches_code=false`) — это отдельная миграция PG, полосой не
  входила; флаг канона обязателен и был применён.

## 4. L1: natural A/B → research 2/2 (PASS)

- A: «Бот проанализируй мои сообщения в чате и скажи, я злобный?» → `response_act=research`,
  `extent=normal`, `structure=answer`, `tone=neutral`, confidence 0.8, 1 попытка.
- B: «…проанализируй сообщения пользователя Ринтаро… злобоный…» (первая строка — выпад в адрес бота)
  → `response_act=research`, 1 попытка. В R2 здесь был `hostile_rebuff`; правило 7 редакции 3
  сработало, принудительной подмены нет.
- `l1_act_rewritten=false` в обоих случаях: это решение канона, а не результат alias-таблицы.
  `analysis_predicate=true`; analysis-тексты в payload **1×1** — ответ режима `serious` реально
  использовал разбор (0/0 vs 1/1 закрыто).
- Case C не форсировался и остался `answer` (см. §7).

## 5. Мета-вступления: 0/8 (PASS)

Закоммиченный анализатор (`de9783ce…`), окно — первые 1–2 предложения первого абзаца, цитаты
вырезаны; тот же анализатор прогнан отдельно по всем raw (`analyze_all.json`).

| Ответ | Вердикт | Категории |
|---|---|---|
| `newA#0`, `newA#1` | ok | announce/leadin/label — пусто |
| `newB#0`, `newB#1` | ok | пусто |
| `new_forced_A#0`, `#1` | ok | пусто |
| `new_forced_B#0`, `#1` | ok | пусто |
| `newC#0` | ok | пусто |
| `oldA#0` | **META** (legacy) | announce + leadin: «Давай посмотрим на твои сообщения.» |
| `oldB#0`, `oldB#1`, `oldA#1` | ok | — |

Итог: **0/8** по восьми «новым» ответам матрицы, **0/9** с case C; по всем 13 ответам — 1/13
(единственный флаг у легаси-дерева). Прошлый прогон — 2/8; целевое 0/8 достигнуто.

## 6. Core, FREQ, payload, закрывающий блок

| Прогон | Core chars / sha12 / in_system | system | FREQ | Директива/Writer (system+user) | no_meta | closing |
|---|---|---|---|---|---|---|
| `newA` | **3294 / `ead77b2ab509` / true** | 14406 `054b072cb874` | true | 1 / 1 (user, system 0) | 1×, plan_block | 1×, после `</Current_Question>`, последний |
| `newB` | 3294 / `ead77b2ab509` / true | 14409 `9889ce83d9f4` | true | 1 / 1 | 1× | 1× / после / последний |
| `newC` | 3294 / `ead77b2ab509` / true | 14377 | true | 0 / 0 | 1× | 1× / после / последний |
| `new_forced_A` | 3294 / `ead77b2ab509` / true | 14406 | true | 1 / 1 | 1× | 1× / после / последний |
| `new_forced_B` | 3294 / `ead77b2ab509` / true | 14406 | true | 1 / 1 | 1× | 1× / после / последний |
| `oldA/oldB` | 2507 / `e62de1fcd7a2` / true | 13863/13866 | true | 0 / 0 / 0 (константы нет) | — | 0 |

- Слои ядра те же: `channel_contract` 3081, `core` 3294, `identity` 5048, `expression` 1069;
  `core.in_system=true` — текст физически в финальном system.
- `no_meta_contract`: `applies=true, count=1, required=1, carrier=plan_block` во всех пяти прогонах
  кандидата; `invalid` пуст, поэтому инварианты 1×1/0×0 не сработали как ошибки.
- Закрывающее требование (184 симв.) стоит в user-части ровно один раз, **после**
  `</Current_Question>` и последним блоком; в system — 0. Self-check подтверждает
  `closing_once_per_payload`, `closing_last_after_current_question`, `closing_only_in_user_part`.
- `PROFANITY_FREQUENT_TEXT` в system 7/7 (`frequent_text=true`, `occasional/off=false`) — режим из
  живого конфига.

## 7. RAG: блок пуст по НЕ-self причине (FAIL приёмки)

`rag_source=service` во всех 7 прогонах; retrieval реальный: `vec_reflected=true`, `vec_dim=3072`,
A и B дают **разные** query и разные наборы (`rows_sha12` `69c975230b9d` vs `3ab839c6f464`),
`db_read_only=true`.

| Прогон | origins в 10 строках | self | после self | после дедупа | block | `rag_empty_reason` | `is_correct` |
|---|---|---|---|---|---|---|---|
| `newA` = `new_forced_A` | derived_belief 2, bot_direct_reply 7, chat_history 1 | 7 | 3 | 3 | **0** `e3b0c44298fc` | **`service_empty`** | **false** |
| `newB` = `new_forced_B` | derived_belief 4, bot_direct_reply 3, chat_history 3 | 3 | 7 | 7 | **0** | **`service_empty`** | **false** |
| `newC` | chat_history 7, voice_transcript 1, bot_self_reply 2 | 2 | 8 | 8 | **951** `4c514b08209f` | — (rendered) | — |
| `oldA` / `oldB` | — (легаси-путь, без detail) | — | — | — | 146 / 0 | — / `no_facts` | — |

Что это значит по продукту (дедукция по коду, не по логу):

1. Self-echo фильтр работает как задумано: 7/10 и 3/10 строк — собственные выводы бота, они не
   попадают в факты; `derived_belief`/`chat_history` остаются.
2. Дедуп против `<Global_Context>` ничего не съедает: после него 3 и 7 фактов.
3. Единственный шаг между «kept непуст» и рендером, который может обнулить список, — F4-реранк
   (`MemoryManager.rerank_rag_facts`, вызов только при `flags.chat_rag_rerank_enabled=True`);
   typed-ветка `MCA_TYPED_RERANKER_ENABLED` по умолчанию ON, валидный пустой выбор → `[]` →
   `_build_rag_block` возвращает `""`. Рендер `build_rag_context` на непустом списке пустым быть не
   может, `_mark_rag_fact`/сортировка ничего не удаляют, cap не обнуляет.
4. Значит блок пуст потому, что **реранк отобрал ноль** из выживших фактов для вопросов A/B, а не
   потому что все строки self-origin. Стенд этого шага не пишет (`candidate_count/selected_count/
   status` отсутствуют в raw) — поэтому это дедукция, а не наблюдение.
5. C в том же процессе и конфиге рендерит блок 951 симв. ⇒ путь рендера и флаги рабочие, разница
   ровно в релевантности фактов под запрос.

**По формулировке полосы критерий не выполнен:** пустой блок не объясняется ни «все строки —
собственные», ни «`no_facts`»; `rag_empty_is_correct=false`. Это либо дефект отбора (реранк рубит
единственные живые факты под разбор), либо приёмка должна переформулировать критерий под
«реранк вернул пусто» — решение Reviewer, не DevOps. Для доказательства нужен один машинный факт в
raw: `rerank_status` + `candidate_count`/`selected_count` (без текстов фактов, §12 Q9).

## 8. Case C (режим не навязывался)

- L1 сам выбрал `answer / compact / chat`, `tone=playful`, mode `casual`, 1 попытка, тот же канон.
- Ответ 218 символов: «Да нет, нормально. Дождь — это единственная хуйня, которая не пытается со
  мной поговорить, когда мне хуёво…» — без мета-вступления, 0/1; короткий ответ не раздувается
  (218 против 230–656 у разборов).
- RAG-блок у C отрендерился (951 симв.), `nostalgia_hint=true`.
- Оценок «плохо/хорошо» не выношу: единственное наблюдение — вопрос бытовой, разбор не включался.

## 9. Baseline `534ac7dd` (тот же harness, без code-canon)

- L1: oldA `analysis` (сырое значение, без нормализации → mode `casual`, analysis-тексты 0/0),
  oldB `clarification`; 1 попытка. Это ровно тот дефект, который лечит кандидат
  (`canonical_response_act`), на легаси-дереве он воспроизводится.
- Core 2507/`e62de1fcd7a2`, system 13863/13866; FREQ true; closing-константы нет (0/0/0).
- RAG: service, 10 строк, oldA блок 146 симв. (`2bd623967c59`), oldB пуст с `no_facts`.
- Мета 1/4 (oldA#0) — база не деградировала, различия объяснимы версией кода.

## 10. Безопасность (прод только читался)

| Параметр | До (11:51:08) | После (11:54:40) |
|---|---|---|
| `local_database.db` mtime / size | 11:45:36.209 / 1 625 980 928 | 11:54:36.441 / 1 626 017 792 |
| `…db-wal` / `…db-shm` | 4 223 032 / 32 768 | 4 223 032 / 32 768 |
| git HEAD / branch | `534ac7dd` / HEAD (detached) | `534ac7dd` / HEAD |
| dirty | 13 | **13** |
| unit `admin_bot` | active, `NRestarts=0`, `ActiveEnter=2026-10-24 21:03:19 UTC` | то же |
| healthz `https://127.0.0.1` / `http://127.0.0.1` | 000 / 308 | 000 / 308 |

Файл БД и WAL дописывает сам бот (тот же паттерн, что в R2); наши соединения read-only по
конструкции (SQLite `mode=ro`, PG `SET SESSION … READ ONLY` + `transaction_read_only=on`,
`db_read_only=true` в каждом raw). Рестартов, checkout, записей в `/var/www/admin_bot` не было;
процессов стенда после — 0; `/tmp/p0c-int3*` вычищен. `https=000`/`http=308` на loopback — как в
прогонах `probes_final3/4`, не регрессия.

## 11. Приёмка по критериям полосы

| Критерий | Факт | Статус |
|---|---|---|
| L1 natural A/B = research / serious | 2/2, raw = norm, `rewritten=false` | **PASS** |
| Мета 0/8 | 0/8 (0/9 с C); oldA 1/4 — легаси | **PASS** |
| Core 3294 / `ead77b2ab509` / in system | 5/5 новых прогонов | **PASS** |
| RAG `rag_source=service` | 7/7 | **PASS** |
| RAG пустой блок объяснён и законен | `service_empty`, `is_correct=false`; не self-origin (3 и 7 живых фактов), C рендерит 951 | **FAIL** |
| FREQUENT из живого конфига | `frequent_text=true` 7/7 | **PASS** |
| Payload 1×1 research / 0×0 answer, `invalid` пуст | 1/1 у A/B/forced, 0/0 у C и легаси; invalid пуст | **PASS** |
| Closing ровно 1× после `</Current_Question>` | 5/5 новых, в system 0, последний блок | **PASS** |
| Exit-фикс стенда | 7/7 `exit_after_summary=yes in 0s`, rc=0 | **PASS** |
| Case C без навязанного режима | `answer/casual`, 218 симв., меты нет | **PASS** (наблюдение §8) |
| Безопасность | HEAD/dirty/unit/health без изменений, 0 процессов | **PASS** |

## 12. Что дальше (без деплоя)

1. **Builder/Reviewer — RAG.** Назвать причину пустого блока для A/B: реранк вернул валидный пустой
   выбор или это дефект отбора. Нужен машинный факт в raw (`rerank_status`, `candidate_count`,
   `selected_count`, без текстов) — тогда `service_empty` перестанет быть «необъяснённым».
   Если Reviewer считает пустой RAG на разборе допустимым — переформулировать критерий явно, а не
   по факту; если нет — вернуть в Builder.
2. **PG-канон L1** остаётся `8261/6c2ddc17c998` против кода `9391/ca1ba3049991`: релиз обязан
   включать миграцию значения (иначе прод будет считать по старому канону).
3. Деплой `fe1e514a` не начинать: RAG-критерий не зелёный, миграция PG не выполнена. Прод остаётся
   `534ac7dd` (2.58.130).

**Сырые данные:** `plans/features/asap-speech-arch/evidence/p0-hotfix/probes_final5/`
(7 raw json, 7 stdout-сводок, `.err`, `.hang.txt` = подтверждение exit-фикса, `stage_sha.txt`,
`selfcheck.json` PASS 40/40, `astcheck.txt`, `state_pre/before/after`, `run.log`, `leftovers.txt`,
`analyze_all.json` — вывод закоммиченного анализатора по всем raw, `summary_lines.txt`,
`sha256.txt`). Локальные скрипты сеанса —
`OPENCODE_WORKFLOW_SCRATCH/adminbot-ccef72c25768/p0c-int5/`.
`@Orchestrator`
