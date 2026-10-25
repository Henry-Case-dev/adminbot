# P0 — LIVE-FINAL-DETERMINISTIC на кандидате `7ca05a92`

- **LANE_ID:** `LIVE-FINAL-DETERMINISTIC` (DevOps, read-only live).
- **Дата:** 2026-10-25, 08:26:28–08:34:35 UTC (локально 20:26–20:34, UTC+12). Один SSH-логин, 486.2 с.
- **Кандидат:** `task/speech-p0-hotfix` @ **`7ca05a92727480c9c1290845cd339b7f80a820c5`**; прод-база `534ac7dda6713fb407e0789fdddfa563251cdab4` (2.58.130).
- **Прод:** HEAD `534ac7dd` до и после, dirty 13 → 13; unit/health не трогались. **Deploy не выполнялся.**
- **Стенд:** `/tmp/p0-final6/new`, `git archive` ровно `7ca05a92` (509 файлов, 24 MB; исключены только `plans/`, `media/`, `extra_images/`, `tests/`). `.env` и `local_database.db` — симлинки на прод.
- **Интерпретатор:** `/var/www/admin_bot/venv/bin/python` 3.12.3 (не системный `python3`).
- **Привязка:** 8/8 пинутых модулей и harness совпали с коммитом по sha256; harness **`d31a2875…`**, `harness_extra` **`227498af…`**, `harness_effective` **`5c9fc4c5…`**; серверный `analysis_final6.py` v1 — **`6f9f7787…`** (его прогнал сервер), в evidence лежит v2 strict **`14fea25e…`** (тот же guard-код + исправленный счётчик markdown-нумерации).
- **Self-check:** **PASS 21/21**, EXIT 0 (`l1_research_fallback_present`, `l2_meta_guard_present`, `l1_temperature_deterministic_zero`, `core_full_not_truncated`, `code_l1_canon_*`).
- **Режим:** read-only PG (`transaction_read_only=on`), SQLite `mode=ro`; Telegram/запись/usage/events не задействованы; ключи не выгружались.
- **Вердикт:** **FAILED** — мета в первом предложении после production-guard **1/16** (E1), нумерация в E (**6/5**). L1 A/B **2/2** raw и effective, A analysis 1×, meta-форма E2 снята, цитаты/Core/RAG/FREQ/alias — PASS.

## 1. SSH и стенд

- **Один логин**, 08:26:28–08:34:35 UTC, 486.2 с; предыдущий сеанс final5 — 07:59 UTC (разрыв 27 мин), fail2ban не сработал, перебора нет.
- Staging собран заново, не переиспользован: `rm -rf /tmp/p0-final6`, загрузка tar, распаковка, симлинки `.env`/`local_database.db`, маркер `PROBE_COMMIT=7ca05a92…`.
- Серверные sha256: 8/8 модулей = ожидаемым из коммита (`chat_prompts d6cba9a7…`, `direct_l1 23d608da…`, `prompt_style_blocks 9e0a5293…`, `response_extent c97c7b33…`, `direct_chat_service 97889b11…`, `summary_memory 1c3810b7…`, `prompt_composer 60fada12…`, `prompt_registry 6ff70744…`), harness/extra/effective/analysis — байт-в-байт локальным.
- **БД:** до `1792916382 / 1624825856`, после `1792917051 / 1624875008` (+49 152 B за 8 мин) — активность живого бота; harness пишет только в `/tmp/p0-final6`.
- **Шум стенда:** `mca_experience.list_lessons` → `AttributeError: 'NoneType' … .db` в stderr всех прогонов (store не инициализирован в harness); `stage_errors={}` во всех 10 прогонах. Известный дефект стенда, не продукта.

## 2. L1: 8 формулировок + forced + effective

| Прогон | mode | plan source | action / response_act | extent / structure | predicate | attempts | L2, симв. |
|---|---|---|---|---|---|---|---|
| raw A | serious | llm | reply / **research** | compact / answer | true | 1 | 275 / 401 |
| raw B | serious | llm | reply / **research** | normal / answer | true | 1 | 574 / 405 |
| eff A | serious | llm | reply / **research** | compact / answer | true | 1 | 352 / 166 |
| eff B | serious | llm | reply / **research** | compact / answer | true | 1 | 263 / 212 |
| C | casual | llm | reply / answer | compact / chat | false | 1 | 123 / 196 |
| D | casual | llm | reply / emotional_reply | compact / chat | false | 1 | 293 / 259 |
| E | deep_research | llm | reply / **research** | detailed / report | true | 1 | 3049 / 2595 |
| F | casual | llm | reply / historical_recall | compact / answer | false | 1 | 207 / 241 |
| forced A | serious | forced | reply / research | normal / answer | true | — | 457 / 663 |
| forced B | serious | forced | reply / research | normal / answer | true | — | 398 / 619 |

- **A/B natural: research 2/2** уже на сыром плане; effective (через committed fallback) — тоже **2/2**. Forced — **2/2**. Malformed/retry: 0; у всех natural `l1_attempts=1`.
- **Fallback не сработал ни разу** (`fallback_calls: before=research, applied=false` для A и B): планировщик в этом прогоне сам вернул research. Offline-матрица на точном дереве коммита: A и B `task_kind=research → applied=true`, C/D/F — `social_chat`/`explanation → applied=false`; т.е. ветка рабочая, но live-доказательства её срабатывания нет.
- **Нестабильность планировщика:** два одинаковых B-запроса дали extent `normal` (raw) и `compact` (eff) при `l1_temperature=0.0`; оба research. Это наблюдение к «детерминированности» L1 — фиксируется, не блокер A/B.
- **Канон:** code **9588**, sha12 **`cc020660ae03`** во всех; PG прода 8261, `6c2ddc17c998`, `pg_matches_code=false` — ожидаемая преддеплойная ступень.
- **E не silent:** `action=reply`, `response_act=research`, `extent=detailed`, `structure=report`, confidence 0.65; 3049/2595 симв., содержательный разбор тем с примерами.
- **F:** `historical_recall`, confidence 0.3, `needs_clarification=false`; текст честный («Да не было там никакого конфликта…», «Да хуй его знает, я не следил»). В final5 маршрут был `clarification` — маршрут нестабилен, живой pre-action может обработать иначе.
- Коммит harness **не применяет** сервисный fallback: он строит payload из сырого плана и не вызывает `DirectChatService._plan_direct_l1`. Для честного замера production-семантики добавлен отдельный стенд `probes_full/harness_effective.py` (патчит только `parse_l1_plan` → `apply_research_fallback(plan, query)`; продукт не менялся, маркировка `stand_wrapper` в JSON). Сырые и effective-прогоны сосуществуют в evidence.

## 3. Payload: Core, analysis, no-meta, quote

| Набор | Core, симв. | Core sha12 | offset | analysis dir/writer | NO_META | QUOTE |
|---|---|---|---|---|---|---|
| eff A, eff B, E, forced A/B | **3294** | **`ead77b2ab509`** | 3083 | **1×1** | 1× | 1× |
| C, D, F | **3294** | **`ead77b2ab509`** | 3083 | 0×0 | 1× | 0 |

- **Core:** ровно 3294, sha12 `ead77b2ab509`, единственное вхождение offset 3083 — в **8/8** primary (и в 2/2 raw диагностических). `manifest.versions.core=0` — известный дефект отчётности harness; проверялся срез `system`.
- Research/effective payload: analysis/quote ровно 1×1×1; casual — 0×0. `extent_scrub_removed=0` во всех; `max_tokens=2400`; обрезания Core нет.

## 4. Мета и цитаты (главные счётчики)

- **Мета в первом предложении: raw 2/16 → после production-guard 1/16. Требование 0/16 — FAIL.**
  - raw E2: «**Окей, давай без лишних прелюдий.**» — guard снял (осталось «По этому отрывку чата картина следующая:»); форма final5 «Ладно, давай по фактам.» больше не воспроизвелась и снимается (проверено офлайн на длинном хвосте).
  - raw/final E1: «**Ну давай, разложу по полочкам, раз уж попросил.**» — guard **не снял**; это первое предложение итогового ответа.
  - Причина: `_L2_META_ANNOUNCE_RE` требует `давай(те)?\s+<глагол-инфинитив>`; здесь после «давай» запятая и форма «разложу». Ведущее «Ну» без запятой тоже не потребляется filler-веткой. Микро-проверка на коде коммита: `«Ну давай, разложу…»` → без изменений; `«Ну, давай, разложу…»` → снимается только «Ну,»; `«Окей, давай без лишних прелюдий.»` → снимается; `«Ладно, давай по фактам. <длинный хвост>»` → снимается. Это узкая дыра guard'а, не откат фикса E2.
- **Цитаты: raw 44 → после guard 26, non-exact 0.** E1 21→12, E2 14→12; forced A 4→1, forced B 4→1; B 1→0; A/C/D/F — 0.
  - 24/26 финальных цитат byte-exact; две (`«что-нибудь разъебали в Перми»`, одна в forced A) — normalized-only совпадения с блоком (production-критерий `_quote_matches_pool` их принимает). Снятые примеры: «вот это пиздато стелит», «старьём», «накрывает», «я умнее вас всех, слушайте сюда».
- **Длины:** B eff 263/212 (raw 574/405); E 3049/2595. B короче final5 (539/643), но это вердикт+обоснование, не обрезка (`extent_scrub_removed=0`, лимит не достигнут).
- **Даты:** 0 годов/месяцев/чисел-дат во всех 16.

## 5. RAG / FREQ / alias

- **RAG (все 8 primary):** `rows=40`, `after_self_filter=40`, `after_dedup=40`, `kept=40`, cap 2000, block **2027** симв., sha12 **`d88fc1c1ec56`**. Маркеры: **18** `(не подтверждено)`, **0** `(предположение)`, **18** `[чат]`, **0** `[Бот]`. Рендер — реальная цепочка сервиса, не самодельный.
- **FREQ:** `frequent_text=true`, `occasional_text=false`, `off_text=false` во всех; PG global `profanity=frequent` rev2, chat `frequent` rev2. Мат фактический, без механической вставки.
- **Alias:** uid `42115912` → **`Макс`** (`source=chat`, global тоже `Макс`); Telegram display `Гипербореец` — не алиас.
- **Прочее:** 0 `[Бот]`, 0 «я уже говорил», 0 дат; нумерация — только E (см. §6 п.2).

## 6. 9 проверок (§5–§6 probes_final2, P0 §1.1/§3)

| # | Проверка | Факт | Вердикт |
|---|---|---|---|
| 1 | Прямой ответ без метавступления | E1 «Ну давай, разложу по полочкам…» — **1/16**; raw 2/16 (E2 снят guard'ом) | **FAIL** (требовалось 0) |
| 2 | Нет навязанной структуры/нумерации | E1 — **6** нумерованных жирных заголовков + 10 ярлыков, E2 — **5** + 6; остальные 6 прогонов — 0. Запрос E перечисляет темы/примеры, т.е. структура частично спровоцирована | **FAIL** по буквальному «0 нумерации»; Reviewer решает, допустима ли нумерация для явного перечисления тем |
| 3 | Нет искусственной драматургии | 0 «однажды/кульминация/в далёком/сценарий»; «сериал/классика жанра» в E — оценка, не выдуманная история | PASS |
| 4 | Нет неподтверждённых дат/цитат | Дат/годов — 0; после guard 26/26 production-exact, 0 non-exact (24/26 byte-exact) | PASS |
| 5 | L2 не выдаёт интерпретацию за историю / self-echo | 0 `[Бот]`, 0 «я уже говорил»; RAG 18 `(не подтверждено)`; F честно оговаривает отсутствие конфликта; E-раздел «моя коронная тема» — самоописание, не история | PASS |
| 6 | FREQUENT — настоящий, без few-shot | `frequent_text=true`, occasional/off=false; PG global/chat `profanity=frequent` rev2 | PASS |
| 7 | Явный разбор — подробно | E 3049/2595 `detailed` — PASS; A/B `research` + analysis 1×1×1, ответы-вердикты 166–401 симв. (длина не критерий) | PASS |
| 8 | Обычный вопрос — коротко | C 123/196, D 293/259, F 207/241; без эссе | PASS |
| 9 | Core и индивидуальность | Core **3294**, sha12 **`ead77b2ab509`**, offset 3083, 8/8; identity-блок 5048 симв. | PASS |

## 7. Находки

- **F1 CLOSED (L1):** A/B natural **2/2** research и raw, и effective; A — `research/compact/serious`, analysis 1×1, NO_META 1×, QUOTE 1×; B/E/forced — research. Открытое наблюдение: fallback ни разу не сработал (план уже research), live-доказательства его ветки нет; offline-матрица на точном дереве это компенсирует лишь частично. Планировщик нестабилен по extent (B: normal vs compact при temp 0.0).
- **F2 OPEN (meta, блокер):** «**Ну давай, разложу по полочкам, раз уж попросил.**» переживает guard. Нужна узкая ветка для «давай, <глагол>» (запятая) и/или «ну давай» без запятой + тест на эту форму; форму E2 не ломать. Затем тот же harness: strict meta 0/16.
- **F3 OPEN (§3, структура):** E даёт нумерованные разделы (6/5) и ярлыки. Директива запрещает нумерацию/разделы/ярлыки без прямой просьбы; запрос E просит перечислить темы с примерами. Буквальная проверка «0 нумерации» — FAIL; решение о допустимости для E — за Reviewer.
- **F4 CLOSED (quotes):** 44 → 26, 0 non-exact; текст при снятии кавычек сохранён.
- **F5 CLOSED (Core):** 3294/`ead77b2ab509`, 8/8, offset 3083.
- **F6 observation (F route):** `historical_recall` conf 0.3 вместо `clarification`; текст честный. Маршрут не подтверждён как стабильный.
- **F7 stand:** `mca_experience.list_lessons` traceback во всех прогонах; `pins.git=ERR` (нет `.git`); `--self-check` печатает JSON с обрезкой `[:3000]` — файл не парсится как JSON, авторитетен EXIT 0 и 21/21 `true`.
- **F8 measurement:** committed harness обходит сервисный fallback; `harness_effective.py` — отдельный стенд, в отчёте оба набора. Reviewer должен учитывать это при приёмке A/B.
- **F9 process:** один SSH-сеанс, read-only, прод не менялся; повторные логины не выполнялись.

## 8. Вердикт и дальше

- **FAILED.** Закрыты: L1 A/B 2/2 (raw+effective), A analysis 1×, quotes, Core, RAG/FREQ/alias, E, C/D/F, даты, драматургия. **Не закрыты:** strict meta 0/16 (1/16) и нумерация в E.
- **Deploy не выполнять.** Прод остаётся **2.58.130 @ `534ac7dd`**; rollback не требуется (изменений на проде не было).
- **Builder:** F2 — узкая ветка guard'а для «Ну давай, разложу…» (+тест, не ломая E2); F3 — не нумеровать/не давать ярлыки, когда просят «какие темы», либо подтвердить у Reviewer, что перечисление тем — явная просьба. После правок — тот же harness (A/B natural 2/2, forced 2/2, repeats 2, `--use-code-l1-canon`) и strict meta 0/16.
- **Reviewer:** строки 1–2 держать FAILED; A/B/A-analysis/quotes/Core/RAG/FREQ/alias/E/C/D/F — PASS; F-route и harness-bypass — наблюдения.
- **PM:** привязать final6 к `7ca05a92`; VERIFIED по meta/структуре не ставить.

## 9. Raw

`probes_final6/`: 10 raw JSON (`raw_new_A/B`, `raw_eff_A/B`, `raw_new_C/D/E/F`, `raw_forced_A/B`) + 10 `.out` + 10 `.err`; `analysis.json` (строгий офлайн-пересчёт v2), `analysis_server_initial.json/.out/.err` (серверный v1; счётчик нумерации не видел markdown-`**1.**`, поэтому там 0 — исправлено в v2), `analysis_offline.out/.err`, `manifest.json` (sha256 всех файлов), `selfcheck_new.txt`, `session.json`, `fallback_matrix.json`, `guard_recheck_final5_texts.json`, `harness_extra.py`, `harness_effective.py`, `analysis_final6.py` (v2 strict, `14fea25e…`), `run_final6.py`.

- `guard_recheck_final5_texts.json` — офлайн-прогон новых guard'ов на **текстах final5**: meta raw 2 → final **0/16**, quotes 39 → 22 (0 non-exact), Core 8/8; подтверждает, что форма E2 закрыта, а E1-дыра — новая.
- Секреты не выгружались; alias — только uid `42115912` и `Макс`.
