# P0C-INT R2 — живой прогон кандидата `67ff463c` (read-only, без деплоя)

**Вердикт: FAILED.** Стенд исполнен целиком (7 прогонов, невалидных нет), но три пункта приёмки
не выполнены: мета-вступления **2/8** (ждали 0/8), natural L1 для A/B дал `answer`/`hostile_rebuff`
вместо `research` (0/2), RAG-блок кандидата **пустой** (`block_chars=0`) при реальном retrieval.
Ядро, FREQ, payload-счётчики, `rag_source=service`, различие наборов A/B и отсутствие невалидных
прогонов — подтверждены. Деплой не производился (запрещён полосой).

- **Кандидат:** `67ff463c215ff1f4fc501e9854c699e7e67e337a` (ветка `task/p0c-int`, worktree
  `C:\Code\Python\adminbot-wt-speech-int`, clean), база сравнения `534ac7dd` (прод 2.58.130, `/var/www/admin_bot`).
- **Стенд:** `probes_full/harness_probe_full.py`, sha256 `aaaa489ae07c3d6b…` (81148 байт, 1559 строк);
  анализатор `probes_full/analyze_l2_meta.py`, sha256 `de9783ce2f685d23…` (18011 байт).
- **Окно:** 2026-10-25 10:06–10:58 UTC (локально 20:06–20:58, UTC+12).

## 1. Привязка: что именно исполнялось

Стейджинг собран `git archive 67ff463c` (без `.git`, без `.env`, без БД): `.py`, `config/`,
`info_text.md`, `probes_full/`, `tools/`, 4 закоммиченных raw для negative-контроля анализатора.
Разложен в `/tmp/p0c-int2` (38 MB), `.env` и `local_database.db` — симлинки на `/var/www/admin_bot`.
Интерпретатор — `/var/www/admin_bot/venv/bin/python` 3.12.3.

| Проверка | Значение |
|---|---|
| `stage_sha.txt`: candidate | `67ff463c` |
| tgz стенда sha256 | `050ec7d20e9bcfb19c3c501f4b59cc23c14d5c451ab942eb9606d63894ea7e78` (11356238 B) |
| harness sha256 (staged) | `aaaa489ae07c3d6bb15e0c60f3eebf5a8e12900e954685b605ec0328a594e8b8` |
| analyzer sha256 (staged) | `de9783ce2f685d23787d44a14b045f7d5d98c3d74677b854ff15503a957d43f8` |
| модули кандидата (11 файлов + `info_text.md`) | sha256 на сервере **совпали** с blob'ами `67ff463c` и с worktree (проверено локально по каждому) |
| `direct_chat_service.py` / `direct_l1.py` | `3c9ecc4d82b36486…` / `0a8dd2e01d56993a…` |
| self-check на сервере | **PASS 37/37**, `code_l1_canon 9288/23aae0c9499d`, `no_use_before_assignment=true`, `modules_under_root=true` |
| `--ast-check` harness | `findings=0` |
| пины git в raw | `ERR:…rev-parse`, `dirty=true` — в стейджинге нет `.git`; привязка держится на `stage_sha.txt` + sha модулей |

### Расхождение с формулировкой полосы (важно)

Полоса требовала harness sha256 = `41650f2c571b22f2…`. Этого файла в кандидате нет:
`41650f2c…` — это `probes_full/harness_probe_full.py` из **другой ветки** `task/p0c-canon-harness`
(коммит `23caab25`, 1063 строки, 52316 байт), она не предок `67ff463c` (общая база `d1a44592`).
Тот harness физически не умеет требуемую командную строку: в нём **нет** ни `--rag-source`,
ни `--use-code-l1-canon` (0 вхождений), нет `analyze_l2_meta`. Исполнялся harness кандидата
(`aaaa489a…`, 1559 строк), потому что только он содержит фикс `a164f6e9` (клиент LLM создаётся
до RAG: строка 1216 против вызова 1219) и AST-guard. Оба sha зафиксированы в отчёте; если
Оркестратор имел в виду именно `41650f2c…`, полосу нужно переформулировать — этой матрицей он
не запускается.

## 2. Соединения (fail2ban-дисциплина)

| # | Время (UTC) | Что | Итог |
|---|---|---|---|
| 1 | 10:06:28–10:07:25 | стейджинг + self-check | **провал по моей вине**: `out/` создавался до `rm -rf /tmp/p0c-int2` и был снесён; ни один прогон не стартовал, прод не тронут |
| 2 | 10:08:18–10:54:28 | матрица с `timeout 900` | A и B дошли до полного JSON, но процесс не завершается → оба съедены таймаутом (30 мин), связь оборвана драйвером |
| 3 | 10:55:07–10:58:03 | продолжение: A/B взяты готовые, остальные 5 прогонов с остановкой сразу после сводки | **успех**, 0 невалидных |

Итого **3 логина**, ни одной неудачной аутентификации, ретраев нет, интервал между логинами
> 1 мин. Один лишний логин — сверх «одного дополнительного на сбой стейджинга»; причина обоих
лишних — ниже (§8), не связано с продом.

## 3. Матрица прогонов

Команда кандидата: `--root /tmp/p0c-int2 --rag-source service --use-code-l1-canon`,
baseline: `--root /var/www/admin_bot --rag-source service` (без code-canon флага).

| Прогон | L1 источник | act / extent / structure | mode | canon | попыток | `invalid` | `rag_source` | block_chars | L2 симв. | мета |
|---|---|---|---|---|---|---|---|---|---|---|
| `newA` (A, natural) | llm | `answer / compact / answer` | casual | code `23aae0c9499d` (9288) | 1 | — | service | **0** | 323, 802 | **1/2** |
| `newB` (B, natural) | llm | `hostile_rebuff / compact / chat` | casual | code `23aae0c9499d` | 1 | — | service | **0** | 449, 321 | 0/2 |
| `newC` (C, natural) | llm | `answer / compact / chat` | casual | code `23aae0c9499d` | 1 | — | service | **0** | 219 | 0/1 |
| `new_forced_A` | forced | `research / normal / answer` | serious | code `23aae0c9499d` | — | — | service | **0** | 598, 602 | 0/2 |
| `new_forced_B` | forced | `research / normal / answer` | serious | code `23aae0c9499d` | — | — | service | **0** | 943, 707 | **1/2** |
| `oldA` (baseline) | llm | `answer / compact / chat` | casual | code `6c2ddc17c998` (8261) | 1 | — | service | 146 | 498, 395 | 0/2 |
| `oldB` (baseline) | llm | `answer / compact / answer` | casual | code `6c2ddc17c998` | 1 | — | service | 146 | 348, 505 | 0/2 |

- Ни одного `invalid`/`fatal`/`stage_errors` в 7 прогонах; `l2_chars` непустые везде.
- PG-сессия: `read_only=on`; SQLite: `mode=ro` (`rag.db_read_only=true`); окно A/B — 64 сообщения,
  `settings_keys=537`, `chat_params=6`, `graph_facts_rows=40`.
- L1-канон кода `9288/23aae0c9499d`, а PG всё ещё `8261/6c2ddc17c998` (`pg_matches_code=false`) —
  поэтому флаг `--use-code-l1-canon` был обязателен; у baseline канон PG и кода совпадают.

## 4. Payload, Core, FREQ

| Прогон | директива / writer / no-meta (итог) | инвариант | Core chars / sha12 / in_system | system | FREQ |
|---|---|---|---|---|---|
| `newA` | 0 / 0 / 1 | 0x0 ✔ (answer) | **3294 / ead77b2ab509 / true** | 14409 `9889ce83d9f4` | true |
| `newB` | 0 / 0 / 1 | 0x0 ✔ | 3294 / ead77b2ab509 / true | 14409 | true |
| `newC` | 0 / 0 / 1 | 0x0 ✔ | 3294 / ead77b2ab509 / true | 14409 | true |
| `new_forced_A` | **1 / 1** / 1 | **1x1 ✔** (research) | 3294 / ead77b2ab509 / true | 14409 | true |
| `new_forced_B` | **1 / 1** / 1 | **1x1 ✔** | 3294 / ead77b2ab509 / true | 14409 | true |
| `oldA` / `oldB` | 0 / 0 / 0 | legacy: константы нет (`applies=false`) | 2507 / e62de1fcd7a2 / true | 13866 `7771dd89a8c7` | true |

- Контракт «без мета-вступления»: `applies=true, count=1, required=1, carrier=plan_block` во всех
  пяти прогонах кандидата. Слой `core` рендерится 3294 и физически входит в system (`in_system=true`),
  identity 5048, expression 1069.
- `PROFANITY_FREQUENT_TEXT` присутствует в system всех 7 прогонов (`frequent_text=true`,
  `occasional=false`, `off=false`) — режим из живого конфига, не few-shot.
- L2 — `deepseek-v4-flash` @ `nano-gpt.com`, `max_tokens=2400`, `temperature=0.7`,
  ответы 2.6–4.9 с; обрезания по лимиту нет (все тексты 219–943 симв. ≪ 2400 токенов).

## 5. RAG

Реальный путь сервиса `DirectChatService._build_rag_block` → `MemoryManager.get_rag_facts`
(`include_direct_reply=True, include_self=True, with_meta=True`), `vec_reflected=true`, `vec_dim=3072`,
таблица `graph_facts_vec`.

| Прогон | query (фактический) | rows | ids | rows_sha12 | block |
|---|---|---|---|---|---|
| `newA` / `new_forced_A` | «Бот проанализируй мои сообщения в чате и скажи, я злобный?» | 10 | 20479, 20476, 21254, 19433, 19173, 18105, 17205, 16698, 16209, 19754 | `69c975230b9d` | **0 символов, `empty=true`** |
| `newB` / `new_forced_B` | «…проанализируй сообщения пользователя Ринтаро… злобоный…» | 10 | 20482, 20263, 19636, 16816, 21254, 18024, 21291, 15434, 20622, 19977 | `3ab839c6f464` | **0 символов** |
| `newC` | «Слушай, а ты дождь любишь…» | 10 | 20957, 18067, 16648, 16576, 16575, 15561, 14970, 19113, 19987, 19773 | `f7ca6fdde775` | **0 символов** |
| `oldA` | тот же, что A | 10 (tuple-контракт) | — (ids только у dict-строк) | — | 146 симв., `2bd623967c59`, `nostalgia_hint=true` |
| `oldB` | тот же, что B | 10 (tuple-контракт) | — | — | 146 симв., тот же sha |

Что подтверждено: `rag_source=service`, retrieval реальный (query доходит, наборы A и B **разные**,
sha и ids различаются), self-echo в блок не попадает — но именно потому, что блок пуст: в
`_build_rag_block` после self-origin фильтра (`direct_chat_service.py:8538-8541`) и
`dedup_rag_vs_global` (`8544-8546`) остаётся ноль фактов для всех трёх запросов, поэтому
`<RAG_Memory>` не рендерится. На проде тот же вызов отдаёт один факт (146 симв.), и он, судя по
разнице путей, отфильтрован кандидатом как self-origin. **Проверить это raw'ом нельзя**: harness
не пишет ни `after_self_filter`, ни origin'ы строк, ни текст блока в service-ветке — это пробел
стенда, а не доказательство. Критерий `rag.block_chars > 0` поэтому **не выполнен**, а причину
надо либо назвать в продукте (self-echo — тогда критерий переформулировать), либо доказать
одним полем в raw.

## 6. Мета-вступления: 2/8 (ждали 0/8)

Детектор `analyze_l2_meta.py` (sha `de9783ce2f685d23…`, self-check PASS на сервере), окно —
первые 1–2 предложения первого абзаца, цитаты вырезаны.

| Ответ | Вердикт | Предложение-носитель | Категории |
|---|---|---|---|
| `newA#1` | **META** | «Давай посмотрим на твои сообщения в этом чате.» | announce + leadin |
| `new_forced_B#0` | **META** | «Давай, разложу.» | announce + leadin |
| остальные 6 (A#0, B#0, B#1, fA#0, fA#1, fB#1) | ok | — | — |
| `newC#0` | ok | — | — |
| `oldA/oldB` (4) | ok | — | — |

Итого по 8 «новым» ответам матрицы (A×2, B×2, forced A×2, forced B×2) — **2/8**, по всем 13 —
2/13. Плюс к прежнему прогону (5/8) стало лучше, но целевое «0/8» не достигнуто: директива
`NO_META_STRUCTURE_TEXT` доезжает до Writer'а ровно один раз (`count=1, required=1`) и всё равно
не удерживает модель в 2 случаях из 8.

## 7. Case C (режим не навязывался)

- L1 сам выбрал `answer / compact / chat`, mode `casual`, 1 попытка, канон кода.
- Ответ 219 символов: «Да мне похуй на дождь, я же не растение и не метеозависимая бабка. Ломает
  меня от других вещей — от того, что Славик тут каждые пять минут описывает свои тактильные
  ощущения как будто он первый человек, открывший одеяло».
- Мета-вступлений нет; длина — самая короткая в матрице (219 против 321–943), т.е. короткий
  бытовой вопрос не раздувается.
- **Находка без оценки «плохо/хорошо»:** текст заканчивается без точки, на «…открывший одеяло»;
  лимит `max_tokens` не достигнут (219 симв.), постобработки/тримминга в стенде нет — похоже на
  собственную остановку модели. Отдаю Reviewer как наблюдение по case C, не как вывод.

## 8. Baseline `534ac7dd` (тот же harness, без code-canon флага)

- L1 natural: `answer/casual` 2/2, канон `6c2ddc17c998` = PG (совпадает).
- Core 2507/`e62de1fcd7a2` против 3294/`ead77b2ab509` у кандидата; system 13866 против 14409.
- Payload: директивы/writer'а нет вовсе (`no_meta` константы в дереве нет) — 0/0/0.
- RAG: service, 10 строк по tuple-контракту (`ids`/`ranks` не пишутся — ограничение стенда для
  легаси-дерева), блок 146 символов, одинаковый для A и B, `nostalgia_hint=true`.
- Мета 0/4, FREQ true — база не деградировала, различия объяснимы версией кода.

## 9. Безопасность (до/после, прод только читался)

| Параметр | До (10:09 / 10:55) | После (10:58) |
|---|---|---|
| `local_database.db` mtime / size | 10:08:06.760 / 1625198592 · 10:50:27.998 / 1625604096 | 10:55:40.367 / 1625665536 |
| `…db-wal` / `…db-shm` | 4194192 / 32768 | 4206552 / 32768 |
| git HEAD / ветка | `534ac7dd` / HEAD (detached) | `534ac7dd` / HEAD |
| dirty | 13 | **13** |
| unit `admin_bot` | active, `NRestarts=0`, `ActiveEnter=2026-10-24 21:03:19 UTC` | то же, без изменений |
| healthz `https://127.0.0.1` / `http://127.0.0.1` | 000 / 308 | 000 / 308 |
| процессов стенда после | — | 0 |

Файл БД и WAL дописывает сам бот (checkpoint/append, между снимками); наши соединения read-only
по конструкции: SQLite `mode=ro`, PG `SET SESSION … READ ONLY` + `transaction_read_only=on`,
`rag.db_read_only=true` в каждом raw. Рестартов, checkout, записей в `/var/www/admin_bot` не было;
стейджинг после упаковки удалён (`STAGING_REMOVED`). В `/tmp` остался только `p0c-int2.tgz`
(11 MB, архив стенда) — убрать не смог без ещё одного логина.

## 10. Инфраструктурные находки (не продукт)

1. **Процесс стенда не завершается.** Все 5+2 прогона печатают финальную сводку и остаются жить
   (`exit_hang_after_summary=yes`, работа 10–25 с, дальше висит). При `timeout` это стоило
   900 с на кейс: сеанс 2 потратил 45 мин на A/B/C. В сеансе 3 процесс убивался через 2 с после
   сводки — JSON к этому моменту уже записан и закрыт. Фикс нужен в harness (закрыть asyncpg-пул
   `bot_persona` и клиентов перед выходом) — иначе каждый живой прогон стоит кратно дороже.
2. **В стейджинге нет `.git`**, поэтому `pins.git` в raw — `ERR…`, `dirty=true`. Привязка держится
   на `stage_sha.txt` (кандидат + sha всех модулей, сверены с blob'ами `67ff463c`) — этого хватает,
   но raw сам по себе не доказывает коммит. Если нужен самодостаточный raw, стенд должен писать
   `--candidate-sha` из переданного значения.
3. **RAG-ветка service не пишет детали отбора** (`after_self_filter`/`kept`/origin'ы/текст блока —
   только в dump-ветке). Из-за этого пустой блок нельзя объяснить по raw (§5).
4. Отдельно: `https://127.0.0.1/healthz` = `000` и до, и после (TLS/SNI на loopback), `http` = 308 —
   это ровно как в прогоне `probes_final3`, не регрессия.

## 11. Приёмка по критериям полосы

| Критерий | Факт | Статус |
|---|---|---|
| `rag_source=service` | service во всех 7 | **PASS** |
| `rag.block_chars > 0` | 0 у всех 5 прогонов кандидата (baseline 146) | **FAIL** |
| `l2_chars` непустые | 13 ответов, 219–943 симв. | **PASS** |
| `invalid` пустой | пусто в 7/7 | **PASS** |
| L1 natural A/B = research | A `answer`, B `hostile_rebuff` (0/2) | **FAIL** |
| forced research A/B | research 2/2, `plan_source=forced` | **PASS** |
| payload 1x1 research / 0x0 answer | 1/1 у forced, 0/0 у answer | **PASS** |
| Core 3294 / `ead77b2ab509` / `in_system` | 5/5 прогонов | **PASS** |
| RAG A ≠ B (реальный retrieval) | ids и `rows_sha12` различаются | **PASS** |
| self-echo отфильтрован | блок пуст ⇒ не наблюдается в тексте; raw не даёт origin'ов | **NOT OBSERVED** |
| FREQUENT присутствует | `frequent_text=true` 7/7 | **PASS** |
| мета 0/8 | **2/8** (`newA#1`, `new_forced_B#0`) | **FAIL** |
| case C без навязанного режима | `answer/casual`, 219 симв., меты нет | **PASS** (с оговоркой §7) |
| безопасность | HEAD/dirty/unit/health без изменений | **PASS** |

## 12. Что дальше (без деплоя)

1. **Builder** — два продуктовых пункта: (а) natural L1 перестал уводить «разбери мои сообщения /
   историю» в `research` (канон тот же `23aae0c9499d`, значит дело в правиле 7/детерминизме
   температуры: 1 попытка, валидный JSON, `answer`/`hostile_rebuff`); (б) директива no-meta
   доезжает 1×, но модель всё равно вставляет подводку в 2 ответах из 8.
2. **Builder/harness** — объяснить пустой RAG-блок: добавить в raw origin'ы отобранных строк и
   счётчики `after_self_filter/after_dedup` в service-ветке; закрыть процесс стенда перед выходом
   (§10.1). Пока этого нет, критерий `block_chars>0` недоказуем и, возможно, противоречит
   P0-правилу «self-echo в факты не попадает» — тогда критерий должен переформулировать Reviewer.
3. **Reviewer** — решить, является ли `answer/hostile_rebuff` на A/B дефектом канона (тогда
   возврат в Builder) или допустимой недетерминированностью при том же каноне (тогда требование
   «research 2/2» в ledger надо ослабить явно, а не по факту).
4. Деплой `67ff463c` не начинать: живые критерии не зелёные. Прод остаётся `534ac7dd` (2.58.130).

**Сырые данные:** `plans/features/asap-speech-arch/evidence/p0-hotfix/probes_final4/`
(7 raw json, 7 stdout-сводок, `.err` образцы, `state_*`, `stage_sha*`, `selfcheck.json`,
`astcheck.txt`, `run.log`, `analyze_l2_meta.txt` = вывод закоммиченного анализатора,
`summary_table.json`, `sha256.txt`). Локальный журнал сеансов и скрипты —
`OPENCODE_WORKFLOW_SCRATCH/adminbot-ccef72c25768/p0c-int4/`.
`@Orchestrator`
