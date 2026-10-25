# P0 — LIVE-FINAL-GUARDS на кандидате `879b1653`

- **LANE_ID:** `LIVE-FINAL-GUARDS` (DevOps, read-only live).
- **Дата:** 2026-10-25, 07:53:25–07:59:03 UTC (локально 19:53–19:59, UTC+12). Первый (неудачный) сеанс — 07:49:43–07:51:25 UTC.
- **Кандидат:** `task/speech-p0-hotfix` @ **`879b16533adab9ddc44220f27047aa61c120d653`**; прод-база `534ac7dda6713fb407e0789fdddfa563251cdab4` (2.58.130).
- **Прод:** HEAD `534ac7dd`, dirty 13 → 13; unit/health не трогались. Deploy не выполнялся.
- **Стенд:** `/tmp/p0-final5/new`; staging из `git archive` ровно `879b1653` (1367 файлов, 7.4 MB tar), после распаковки и прогонов — 1381 файл (добавлены `__pycache__`), 34 MB. `.env` и `local_database.db` — симлинки на прод.
- **Интерпретатор:** `/var/www/admin_bot/venv/bin/python` 3.12.3 (не системный `python3`).
- **Пробник:** `probes_full/harness_probe_full.py` из коммита, sha256 **`3c75652c15e5d984b17196769965d44186ca7af127455f8c1584528e10718dbd`**; `harness_extra.py` **`227498afdb7e155b0327340405be3b15a72c7fbdd3ca79ce3b1de5b0f47a0ea1`**.
- **Self-check:** **PASS 20/20** на стенде (`selfcheck_new.txt`), включая `l1_temperature_deterministic_zero`, `l2_meta_guard_present`, `l2_quote_guard_present`, `core_full_not_truncated`.
- **Режим:** read-only PG (`transaction_read_only=on`), SQLite `mode=ro`; Telegram/запись/usage/events не задействованы; ключи не выгружались.
- **Вердикт:** **FAILED** — L1 A/B = **1/2** (A снова `answer/compact`), мета в первом предложении после production-guard = **1/16** (E2 «Ладно, давай по фактам.»). Цитаты (0 non-exact), Core 3294/`ead77b2ab509`, E, RAG/FREQ/alias, C/D/F — PASS.

## 1. SSH и стенд

- **Два логина, это процессное нарушение цели «один SSH».**
  - Попытка 1, 07:49:43–07:51:25 UTC (102.1 с): системный `python3` без зависимостей приложения — self-check упал на `aiosqlite`, пробники на `dotenv`, анализ на `aiogram`. **0 LLM-вызовов**, прод не менялся, staging только создан.
  - Попытка 2, 07:53:25–07:59:03 UTC (337.7 с): `/var/www/admin_bot/venv/bin/python` 3.12.3; 8 проб + анализ. Прод не менялся.
  - Пауза между логинами 2 мин; fail2ban не сработал, повторного auth-подбора не было. Это DevOps-ошибка выбора интерпретатора, не продукт.
- **Staging:** 8 пинутых модулей на сервере совпали с локальным кандидатом 8/8: `chat_prompts d6cba9a7…`, `direct_l1 aca23de7…`, `prompt_style_blocks 9e0a5293…`, `response_extent c97c7b33…`, `direct_chat_service 03b50c2e…`, `summary_memory 1c3810b7…`, `prompt_composer 60fada12…`, `prompt_registry 6ff70744…`. У staging нет `.git` — `pins.git=ERR` ожидаемо; привязка к коммиту подтверждена архивом/хешами.
- **БД:** до `1792914211 / 1624621056`, после `1792914963 / 1624690688` (+69 632 B за 12.5 мин). Это активность живого бота; harness открывает SQLite `mode=ro`, PG read-only, прямых записей стенда нет.
- **Шум стенда:** `mca_humor_feedback.list_lessons` → `AttributeError: 'NoneType' … .db` в stderr всех прогонов (store не инициализирован в harness); `stage_errors={}`, `lessons_block` не влияет на Writer. Известный дефект стенда.

## 2. L1: 8 формулировок + forced

| Прогон | Запрос | plan source | action / response_act | extent / structure | mode | predicate | attempts | L2, симв. |
|---|---|---|---|---|---|---|---|---|
| new A | «Бот проанализируй мои сообщения… я злобный?» | llm | reply / **answer** | compact / answer | casual | **false** | 1 | 515 / 546 |
| new B | «…проанализируй сообщения Ринтаро…» | llm | reply / **research** | normal / answer | serious | true | 1 | 539 / 643 |
| new C | «…дождь любишь или тебя от него ломает?» | llm | reply / banter | compact / chat | casual | false | 1 | 279 / 199 |
| new D | «…я тебе уже надоел…?» | llm | reply / emotional_reply | compact / chat | casual | false | 1 | 201 / 369 |
| new E | «Разбери подробно по этому чату… с примерами» | llm | reply / **research** | detailed / report | deep_research | true | 1 | 2178 / 2490 |
| new F | «…конфликт в чате на прошлой неделе…» | llm | clarification | compact / chat | casual | false | 1 | 158 / 192 |
| forced A | A | forced | reply / research | normal / answer | serious | true | — | 118 / 727 |
| forced B | B | forced | reply / research | normal / answer | serious | true | — | 543 / 482 |

- **A/B natural: research 1/2.** A — `answer`, `compact`, confidence 0.85, payload без analysis-блока (0/0); B — `research`, `normal`, analysis 1/1. Forced A/B — 2/2 research. A/B по одной валидной L1-попытке, malformed/retry нет.
- Канон: code **9588**, sha12 **`cc020660ae03`** во всех 8; PG прода 8261, `6c2ddc17c998`, `pg_matches_code=false` — ожидаемая преддеплойная ступень.
- **A не исправлен температурой:** self-check подтверждает `l1_temperature(None)==0.0`; harness не сохраняет фактическую температуру запроса. Даже при детерминированном выборе A ушёл в `answer`; это семантический дефект L1-канона/контекста, а не длины и не постобработки. Ответ A (515/546) содержит разбор истории, но маршрут и payload — `answer/compact`, приёмочный критерий «A/B research 2/2» не выполнен.
- E: `action=reply`, `response_act=research`, `extent=detailed`, `structure=report`, confidence 0.7 — **не silent**; 2178/2490 симв., содержательный.
- F: `clarification`, `needs_clarification=true`; текст честный («Да ни хуя там не было…», «Без понятия, я за этим не слежу»), без выдуманных участников. Маршрут отличается от прежнего `historical_recall`; в проде pre-action может обработать clarification иначе — это наблюдение, не доказанный PASS маршрута.

## 3. Payload: Core, analysis, no-meta, quote

| Прогон | Core, симв. | Core sha12 | offset | analysis dir/writer | NO_META | QUOTE |
|---|---|---|---|---|---|---|
| new A/C/D/F | **3294** | **`ead77b2ab509`** | 3083 | 0/0 (A — следствие `answer`) | 1× | 0 |
| new B/E, forced A/B | **3294** | **`ead77b2ab509`** | 3083 | **1/1** | 1× | 1× |

- **Core:** ровно **3294** симв., sha12 **`ead77b2ab509`**, единственное вхождение offset **3083** — во всех 8 прогонах. `manifest.versions.core=0` — известный дефект отчётности harness; проверялся срез `system` и `layers[]`.
- `ANALYSIS_DIRECTIVE_TEXT`/`ANALYSIS_WRITER_TEXT`: research (B/E/forced) — **1×1**, casual (A/C/D/F) — **0×0**. A ошибочно в 0×0 из-за маршрута `answer` — это и есть открытый F1.
- `NO_META_STRUCTURE_TEXT` — ровно **1×** в каждом new/forced payload. `QUOTE_FIDELITY_TEXT` — ровно **1×** на research/deep payload, **0** на casual.
- `extent_scrub_removed=0` во всех; `max_tokens=2400`; обрезания текста нет.

## 4. Мета и цитаты (главные счётчики)

- **Мета в первом предложении: raw 2/16, после production-guard 1/16. Требование 0/16 — FAIL.**
  - raw E1: «Ок, давай разложу этот цирк по полочкам.» — guard снял.
  - raw E2: «**Ладно, давай по фактам.**» — guard **не снял**; это первое предложение итогового ответа. Директива прямо запрещает начинать с «ладно»/«давай»; дыра в `_L2_META_ANNOUNCE_RE` (нет ветки «ладно + давай» без глагола из списка).
  - Остальные 14/16 первых предложений — по существу (A1 «Ты не злобный…», B1 «Да хуй его знает…», C1 «Да бля, дождь…», D1 «Слушай, если бы…», F1 «Да ни хуя там не было…», forced A/B — прямые ответы).
- **Цитаты: raw 39, из них 17 не-exact; после guard 22, все 22 exact, 0 non-exact.**
  - Примеры снятых кавычек: «вот это пиздато, а то говно, слушай сюда», «когда фотосет?», «меня не ценят, а я стараюсь», «человеком-новостью», «жертвой», «старьё какое-то», «я генератор контента».
  - Текст при снятии кавычек сохранён; даты/годы — 0 (ложное срабатывание `май` внутри «смайликами» устранено строгой границей слова).
- **Длины B/E:** B 539/643; E 2178/2490. E1 заканчивается «И так по кругу» без точки, но `extent_scrub_removed=0`, лимит не достигнут — это не обрезка, а естественное окончание модели.

## 5. RAG / FREQ / alias

- **RAG new/forced:** `rows=40`, `after_self_filter=40`, `after_dedup=40`, `kept=40`, cap 2000, block **2027** симв., sha12 **`d88fc1c1ec56`** во всех 8. Маркеры: **18** `(не подтверждено)`, **0** `(предположение)`, **18** `[чат]`, **0** `[Бот]`. Отличие от `probes_final4` (39/4) — живое состояние `graph_facts`, не регрессия; участие и provenance-маркировка подтверждены.
- **FREQ:** PG global и chat `profanity=frequent`, revision 2; `frequent_text=true`, `occasional_text=false`, `off_text=false` во всех. Мат фактический, без механической вставки.
- **Alias:** uid `42115912` → **`Макс`** (`source=chat`, global тоже `Макс`), Telegram display `Гипербореец` — не алиас. Регрессии нет.
- **Даты/структура/self-echo:** 0 дат и годов; 0 нумерованных строк/списков; 0 `[Бот]`, 0 «я уже говорил».

## 6. 9 проверок (§5–§6 probes_final2, P0 §1.1/§3)

| # | Проверка | Факт | Вердикт |
|---|---|---|---|
| 1 | Прямой ответ без метавступления | E2 «Ладно, давай по фактам.» — **1/16**; raw 2/16 (E1 снят guard'ом) | **FAIL** (требовалось 0) |
| 2 | Нет навязанной структуры/нумерации | 0 нумерованных строк и 0 списков во всех 16; E — связный текст с жирными метками, без разделов | PASS |
| 3 | Нет искусственной драматургии | 0 «однажды/кульминация/в далёком»; F «Да ни хуя там не было…» | PASS |
| 4 | Нет неподтверждённых дат/цитат | Дат/годов — 0; после guard 22/22 цитаты exact, 0 non-exact | PASS |
| 5 | L2 не выдаёт интерпретацию за историю / self-echo | 0 `[Бот]`, 0 «я уже говорил»; RAG 18 `(не подтверждено)`; F честно оговаривает отсутствие конфликта | PASS |
| 6 | FREQUENT — настоящий, без few-shot | `frequent_text=true`, occasional/off=false; PG global/chat `profanity=frequent` rev2; мат фактический | PASS |
| 7 | Явный разбор — подробно | E 2178/2490 — PASS; B 539/643 research — PASS; **A — `answer/compact`, 0 analysis, 515/546** | **FAIL для A** (B/E PASS) |
| 8 | Обычный вопрос — коротко | C 279/199, D 201/369; без эссе | PASS |
| 9 | Core и индивидуальность | Core **3294**, sha12 **`ead77b2ab509`**, offset 3083, 8/8; identity 5048 | PASS |

## 7. Находки

- **F1 OPEN (L1, блокер):** A natural = `answer/compact`, predicate false, 0/0 analysis, 515/546. A/B = **1/2** research. Детерминированная температура сама по себе маршрут не исправила; нужна правка семантики L1-канона (без хардкода фраз), затем тот же harness A/B 2/2 + forced 2/2.
- **F2 OPEN (meta, блокер):** E2 «Ладно, давай по фактам.» переживает guard; `_L2_META_ANNOUNCE_RE` не покрывает «ладно + давай» без глагола из списка. Нужен узкий guard/правило и тест на эту форму; требование 0/16 не выполнено.
- **F3 CLOSED (quotes):** 39 → 22, все exact, 0 non-exact; текст не режется. Прежний F3 final4 закрыт на этом прогоне.
- **F4 CLOSED (Core):** 3294/`ead77b2ab509`, 8/8, offset 3083.
- **F5 observation (forced A):** forced A1 118 симв. — прямой вердикт без разбора, forced A2 727. Плана research достаточно, но Writer один сэмпл сделал коротким; по §1.1 длина не критерий, поэтому не отдельный блокер, но Reviewer стоит учесть.
- **F6 observation (F route):** `clarification/needs_clarification=true`, текст честный. Маршрут не `historical_recall`; в живом pre-action поведение может отличаться. Не считать PASS маршрута без отдельной проверки.
- **F7 stand:** `mca_humor_feedback.list_lessons` traceback (`store=None`) во всех прогонах; `pins.git=ERR` из-за отсутствия `.git`; `manifest.versions.core=0`. Всё — известные дефекты стенда, не продукта.
- **F8 process:** два SSH-логина: первый — системный `python3` без зависимостей, 0 LLM, прод не менялся; второй — рабочий. Цель «ровно один SSH» не выполнена; fail2ban не сработал.

## 8. Вердикт и дальше

- **FAILED.** Закрыты: quotes, Core, E, RAG/FREQ/alias, C/D/F, даты, структура. **Не закрыты:** L1 A/B 2/2 и meta 0/16.
- **Deploy не выполнять.** Прод остаётся **2.58.130 @ `534ac7dd`**; rollback не требуется (изменений на проде не было).
- **Builder:** F1 — маршрут A (семантика, не температура); F2 — guard/правило для «Ладно, давай по фактам» + тест. Затем тот же `probes_full/harness_probe_full.py` (A/B natural 2/2, forced 2/2, repeats 2, `--use-code-l1-canon`) и strict meta 0/16.
- **Reviewer:** строки 1 и 7 держать FAILED; quotes/Core/RAG/FREQ/alias/E/C/D/F — PASS; F-route — наблюдение.
- **PM:** привязать final5 к `879b1653`, не ставить VERIFIED по L1/meta; release-gate не обходить.

## 9. Raw

`probes_final5/`: 8 raw JSON (`raw_new_A/B/C/D/E/F`, `raw_forced_A/B`) + 8 `.out` + 8 `.err`, `analysis.json`, `manifest.json` (sha256 всех файлов), `selfcheck_new.txt`, `session_attempt1_failed.json`, `session_attempt2.json`, `analysis_server_initial.out/err`, `analysis_final5.py`, `harness_extra.py`.

- `analysis.json` — финальный строгий пересчёт на скачанных raw; `analysis_server_initial.out` — серверный первичный счётчик (без strict-детектора «ладно/давай»), поэтому там meta 0/16; строгий счёт 1/16.
- Секреты не выгружались; alias — только uid `42115912` и `Макс`.
