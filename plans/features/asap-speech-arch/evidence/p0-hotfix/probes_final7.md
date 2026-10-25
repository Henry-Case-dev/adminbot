# P0 — LIVE-META-FINAL на кандидате `134ac385`

- **LANE_ID:** `LIVE-META-FINAL` (DevOps, read-only live). Без Telegram и без деплоя.
- **Дата:** 2026-10-25, 08:53:42–09:01:12 UTC (локально 20:53–21:01, UTC+12). **Один SSH-логин**, 450.4 с.
- **Кандидат:** `task/speech-p0-hotfix` @ **`134ac3856f8f39ea0df3b88facbf67a422ad8c5d`**; прод-база `534ac7dda6713fb407e0789fdddfa563251cdab4` (2.58.130).
- **Прод:** HEAD `534ac7dd` до и после, dirty 13 → 13; unit/health не трогались. **Deploy не выполнялся**, rollback не требуется.
- **Стенд:** `/tmp/p0-final7/new`, `git archive` ровно `134ac385` (529 записей / 509 файлов, 24 MB; исключены `plans/`, `tests/`, `media/`, `extra_images/`). `.env` и `local_database.db` — симлинки на прод; маркер `PROBE_COMMIT=134ac385…`.
- **Интерпретатор:** `/var/www/admin_bot/venv/bin/python` 3.12.3.
- **Привязка:** 8/8 пинутых модулей и harness совпали с коммитом по sha256; harness **`d31a2875…`**, `harness_extra` **`227498af…`**, `harness_effective` **`5c9fc4c5…`**, `analysis_final7.py` **`e6a3c363…`**, `guard_check_final7.py` **`9672549c…`**. Архив — `be0442b4…`.
- **Self-check:** **PASS 21/21**, EXIT 0 (`l1_research_fallback_present`, `l2_meta_guard_present`, `l1_temperature_deterministic_zero`, `core_full_not_truncated`, `code_l1_canon_*`).
- **Режим:** read-only PG (`transaction_read_only=on`), SQLite `mode=ro`; Telegram/запись/usage/events не задействованы; ключи не выгружались.
- **Вердикт:** **FAILED** — strict-мета в первом предложении **1/16**, с учётом обращения **2/16** (обе — E). Требование **0/16** не выполнено. Остальное (L1 A/B, A analysis, E, quotes, Core, RAG/FREQ/alias, C/D/F, даты) — PASS.

## 1. SSH и стенд

- **Один логин**, 08:53:42–09:01:12 UTC, 450.4 с; отдельных recon/повторных логинов не было. Предыдущий сеанс final6 закончился 08:34 UTC.
- Staging собран заново, не переиспользован: `rm -rf /tmp/p0-final7`, загрузка tar, распаковка, симлинки `.env`/`local_database.db`, маркер коммита.
- Серверные sha256: 8/8 модулей = ожидаемым из коммита (`chat_prompts d6cba9a7…`, `direct_l1 23d608da…`, `prompt_style_blocks 9e0a5293…`, `response_extent c97c7b33…`, **`direct_chat_service 96811474…`** — единственный изменённый модуль, `summary_memory 1c3810b7…`, `prompt_composer 60fada12…`, `prompt_registry 6ff70744…`), harness/extra/effective/analysis/guard — байт-в-байт локальным.
- **БД:** до `1792918062 / 1624915968`, после `1792918741 / 1624977408` (+61 440 B за 7.5 мин) — активность живого бота; harness пишет только в `/tmp/p0-final7`.
- **Шум стенда:** `mca_experience.list_lessons` → `AttributeError: 'NoneType' … .db` в stderr всех прогонов; `stage_errors={}` во всех 10 прогонах. Тот же известный дефект стенда, не продукта.

## 2. L1: A/B + forced + C/D/E/F

| Прогон | mode | plan source | action / response_act | extent / structure | predicate | attempts | L2, симв. |
|---|---|---|---|---|---|---|---|
| raw A | serious | llm | reply / **research** | compact / answer | true | 1 | 575 / 270 |
| raw B | serious | llm | reply / **research** | compact / answer | true | 1 | 626 / 283 |
| eff A | serious | llm (fallback **applied**) | reply / **research** | compact / answer | true | 1 | 372 / 260 |
| eff B | serious | llm (fallback not applied) | reply / **research** | compact / answer | true | 1 | 563 / 165 |
| C | casual | llm | reply / answer | compact / chat | false | 1 | 171 / 248 |
| D | casual | llm | reply / emotional_reply | compact / chat | false | 1 | 99 / 118 |
| E | deep_research | llm | reply / **research** | detailed / report | true | 1 | 2744 / 2103 |
| F | serious | llm | reply / **research** | normal / answer | true | 1 | 98 / 271 |
| forced A | serious | forced | reply / research | normal / answer | true | — | 523 / 398 |
| forced B | serious | forced | reply / research | normal / answer | true | — | 475 / 325 |

- **A/B natural: research 2/2** на сыром плане; effective — тоже **2/2**. Forced — **2/2**. Malformed/retry: 0; у natural `l1_attempts=1`.
- **Fallback:** eff A — `before=answer, after=research, applied=true`; eff B — `before=research, applied=false` (план уже research). Offline-ветка fallback на этом прогоне сработала в A, т.е. live-доказательство ветки теперь есть.
- **E не silent:** `action=reply`, `response_act=research`, `extent=detailed`, `structure=report`, confidence 0.85; 2744/2103 симв., содержательный разбор тем с примерами.
- **F:** в этот раз `research` (в final6 был `historical_recall`), confidence 0.3, `needs_clarification=false`; текст честный («Понятия не имею, я за этим не следил»), 98/271. Маршрут нестабилен — наблюдение.
- **Канон:** code **9588**, sha12 **`cc020660ae03`** во всех; PG прода 8261, `6c2ddc17c998`, `pg_matches_code=false` — ожидаемая преддеплойная ступень.

## 3. Payload: Core, analysis, no-meta, quote

| Набор | Core, симв. | Core sha12 | offset | analysis dir/writer | NO_META | QUOTE |
|---|---|---|---|---|---|---|
| eff A/B, E, F, forced A/B | **3294** | **`ead77b2ab509`** | 3083 | **1×1** | 1× | 1× |
| C, D | **3294** | **`ead77b2ab509`** | 3083 | 0×0 | 1× | 0 |

- **Core:** ровно 3294, sha12 `ead77b2ab509`, единственное вхождение offset 3083 — в **8/8 primary** (и в 2/2 raw диагностических). `manifest.versions.core=0` — известный дефект отчётности harness; проверялся срез `system`.
- `extent_scrub_removed=0` во всех; `max_tokens=2400`; обрезания Core нет; identity-блок 5048 симв.
- F теперь идёт research-путём и получает analysis/quote 1×1; ответ при этом короткий (98/271).

## 4. Мета и цитаты (главные счётчики)

- **Strict-мета в первом предложении: raw 1/16 → после production-guard 1/16. Требование 0/16 — FAIL.**
  - E repeat 1: «**Ладно, смотри.**» — guard **не снял** (`announce_removed=false`, `filler_removed=false`).
  - E repeat 2: «**Макс, ну давай, раз уж попросил.**» — strict-детектор не видит из-за обращения; с учётом обращения это та же мета → **2/16**.
  - В live старые формы final6 (E1 «Ну давай, разложу по полочкам…», E2 «Окей, давай без лишних прелюдий.») **не воспроизвелись**. Офлайн на точном коде коммита обе старые формы снимаются ровно одним предложением, тело байт-в-байт (`guard_check.json`: PASS). Т.е. фикс `134ac385` закрыл старую форму, но live-модель выдала новые.
- **Цитаты: raw 44 → после guard 28, non-exact 0.** 27/28 byte-exact, одна — normalized-only совпадение (production-критерий `_quote_matches_pool` её принимает). E 22→12 и 11→11; B 4→4; forced B 1→1; A/C/D/F — 0. Снятые примеры E: «ой бля, старьё», «информативным видосам», «вменяемый в жизни», «Одеяло пиздатое мягкое».
- **Длины:** B 563/165; E 2724/2099. B короче/длиннее от повтора, но это вердикт+обоснование, не обрезка (`scrub_removed=0`, лимит не достигнут).
- **Даты:** 0 годов/месяцев/чисел-дат во всех 16. **Self-echo:** 0 «я уже говорил»; **[Бот]:** 0.
- **Нумерация:** только E — repeat 1: 5 жирных нумерованных заголовков + 6 жирных ярлыков; repeat 2: 0 нумерованных + 6 ярлыков; в остальных 12 текстах — 0. Запрос E явно просит перечислить темы с примерами; по критерию lane «numbering only if explicit (E)» это допустимо (буквальное «0 нумерации» не выполнено).

## 5. RAG / FREQ / alias

- **RAG (все 8 primary):** `rows=40`, `kept=40`, cap 2000, block **2027** симв., sha12 **`d88fc1c1ec56`**. Маркеры: **18** `(не подтверждено)`, **0** `(предположение)`, **18** `[чат]`, **0** `[Бот]`. Рендер — реальная цепочка сервиса.
- **FREQ:** `frequent_text=true`, `occasional_text=false`, `off_text=false` во всех; PG global `profanity=frequent` rev2, chat `frequent` rev2. Мат фактический.
- **Alias:** uid `42115912` → **`Макс`** (`source=chat`, global тоже `Макс`); Telegram display `Гипербореец` — не алиас.

## 6. 9 проверок (§5–§6 probes_final2, P0 §1.1/§3)

| # | Проверка | Факт | Вердикт |
|---|---|---|---|
| 1 | Прямой ответ без метавступления | strict **1/16** («Ладно, смотри.»); с обращением **2/16** (E2 «Макс, ну давай, раз уж попросил.»); guard снял 0 live-фраз | **FAIL** (требовалось 0) |
| 2 | Нет навязанной структуры/нумерации | Нумерация только E: 5 заголовков + 6 ярлыков (r1), 0 + 6 ярлыков (r2); в остальных 12 — 0. E явно просит перечислить темы | **PASS** по критерию «только при явной просьбе»; буквальное «0» в E не выполнено |
| 3 | Нет искусственной драматургии | 0 «однажды/кульминация/в далёком/сценарий/драматизация»; «драма» в E — ярлык темы чата, не выдуманная история | PASS |
| 4 | Нет неподтверждённых дат/цитат | Дат/годов — 0; 28/28 production-exact, 0 non-exact (27 byte-exact, 1 normalized) | PASS |
| 5 | L2 не выдаёт интерпретацию за историю / self-echo | 0 `[Бот]`, 0 «я уже говорил»; RAG 18 `(не подтверждено)`; F честно говорит, что не следил; E — разбор чата | PASS |
| 6 | FREQ — настоящий, без few-shot | `frequent_text=true`, occasional/off=false; PG global/chat `frequent` rev2 | PASS |
| 7 | Явный разбор — подробно | E 2724/2099 `detailed/report`, research, analysis 1×1, не silent | PASS |
| 8 | Обычный вопрос — коротко | C 171/248, D 99/118, F 98/271; без эссе | PASS (F теперь research — наблюдение) |
| 9 | Core и индивидуальность | Core **3294**, sha12 **`ead77b2ab509`**, offset 3083, 8/8; identity 5048 | PASS |

## 7. Находки

- **F1 CLOSED (старые meta-формы):** exact final6 E1/E2 снимаются новым guard'ом ровно на одно предложение, тело байт-в-байт; негативные «Ну давай в субботу», «Ну давай по фактам: …», «Ну давай, по фактам: …» не режутся (`guard_check.json` PASS).
- **F2 OPEN (meta, блокер):** live дал две новые формы — «**Ладно, смотри.**» и «**Макс, ну давай, раз уж попросил.**». Первая не покрыта filler/announce-ветками; вторая не покрыта из-за обращения и отсутствия глагола-анонса. Нужна узкая ветка на «ладно/ок, смотри/гляну…» и на «[Имя,] ну давай, раз уж попросил» без глагола, плюс тесты; затем тот же harness (strict meta 0/16).
- **F3 observation (E structure):** нумерация только в E и только при явной просьбе перечислить темы; Reviewer должен подтвердить, что это допустимо, либо Builder уберёт нумерацию и в E.
- **F4 CLOSED (quotes):** 44 → 28, 0 non-exact; снятые цитаты сохранили текст.
- **F5 CLOSED (Core):** 3294/`ead77b2ab509`, 8/8, offset 3083.
- **F6 observation (F route):** F — `research` conf 0.3 (в final6 — `historical_recall`); ответ честный и короткий, но маршрут нестабилен.
- **F7 stand:** `mca_experience.list_lessons` traceback во всех прогонах; `pins.git=ERR` (нет `.git`); `--self-check` печатает JSON с обрезкой `[:3000]` — авторитетен EXIT 0 и 21/21 `true`.
- **F8 process:** один SSH-сеанс, read-only, прод не менялся; повторных логинов не было.

## 8. Вердикт и дальше

- **FAILED.** Закрыты: L1 A/B 2/2 (raw+effective), A analysis 1×, E, quotes, Core, RAG/FREQ/alias, C/D/F, даты, драматургия, старая meta-форма. **Не закрыто:** strict meta 0/16 (1/16; с обращением 2/16).
- **Deploy не выполнять.** Прод остаётся **2.58.130 @ `534ac7dd`**; rollback не требуется (изменений на проде не было).
- **Builder:** F2 — покрыть «Ладно, смотри.» и «[Имя,] ну давай, раз уж попросил» (+тесты, не ломая negative-кейсы); F3 — при необходимости убрать нумерацию в E или подтвердить у Reviewer. После правок — тот же harness (A/B natural 2/2, forced 2/2, `--use-code-l1-canon --repeats 2`) и strict meta 0/16.
- **Reviewer:** строку 1 держать FAILED; строку 2 — PASS с оговоркой E; A/B/A-analysis/quotes/Core/RAG/FREQ/alias/E/C/D/F — PASS; F-route и harness-bypass — наблюдения.
- **PM:** привязать final7 к `134ac385`; VERIFIED по meta не ставить.

## 9. Raw

`probes_final7/`: 10 raw JSON (`raw_new_A/B`, `raw_eff_A/B`, `raw_new_C/D/E/F`, `raw_forced_A/B`) + 10 `.out` + 10 `.err`; `analysis.json` (строгий офлайн-пересчёт), `analysis.out/.err`, `guard_check.json/.err` (exact final6 E1/E2 + negatives), `meta_gap_check.json` (strict 1/16, с обращением 2/16; live-формы guard'ом не сняты), `selfcheck_new.txt`, `session.json`, `manifest.json`, `run_final7.py`, `analysis_final7.py`, `guard_check_final7.py`, `meta_gap_check.py`, `harness_extra.py`, `harness_effective.py`.

- `manifest.json` — sha256 всех файлов evidence, кандидат, архив, стенд, binding.
- Секреты не выгружались; alias — только uid `42115912` и `Макс`.
