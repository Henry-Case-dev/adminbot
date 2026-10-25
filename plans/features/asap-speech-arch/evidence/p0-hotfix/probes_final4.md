# P0 — LIVE-FINAL-META-SILENT на кандидате `59922de5`

- **LANE_ID:** `LIVE-FINAL-META-SILENT` (DevOps, read-only live).
- **Дата:** 2026-10-25, 06:59:00–07:04:29 UTC (локально 18:59–19:04, UTC+12).
- **Кандидат:** `task/speech-p0-hotfix` @ **`59922de52461129ac2e10a66c472d699587cf860`**; код `c0d5a3d3fc65f15a81f337bd322d1dd9ff2c226d` — предок кандидата.
- **Прод (old):** `/var/www/admin_bot` @ **`534ac7dda6713fb407e0789fdddfa563251cdab4`** (2.58.130), dirty 13 → 13, HEAD не менялся.
- **Стенд:** `/tmp/p0-final4/new`, 421 файл, 14 MB; `.env` и `local_database.db` — симлинки на прод; staging sha256 `42c1d36c…`.
- **Пробник:** `probes_full/harness_probe_full.py` из кандидата, sha256 **`caefd7bc5631d82be86dbd68b53108bdba32fcd68d37bf2f9b10aa8214488425`**; `--self-check` = **PASS 17/17** на сервере; 8 пинутых модулей совпали с локальными 8/8.
- **Дополнительные формулировки:** тонкий `harness_extra.py` sha256 **`227498afdb7e155b0327340405be3b15a72c7fbdd3ca79ce3b1de5b0f47a0ea1`**; подменяет только текущую реплику в окне A, harness и продуктовый код не меняет.
- **Режим:** read-only PG (`transaction_read_only=on`), SQLite `mode=ro`; Telegram/запись/usage/events не задействованы; deploy не выполнялся, ключи не выгружались.
- **Вердикт:** **FAILED** — L1 A/B = **1/2** (A ушёл в `answer`), no-meta = **3/16** первых предложений, quote-rule нарушен (26/45 кавычек без точного источника). E, Core, RAG, FREQ, alias — PASS.

## 1. SSH и стенд

- **Два логина.** Первый, 06:57 UTC, упал на локальном пути к staging-архиву **до** upload/удалённых команд/LLM (0 вызовов); второй, 06:59–07:04:29 UTC, — рабочий, 329.0 с. Прод не менялся ни в одном.
- Это нарушает требование «ровно один SSH-сеанс»; причина — локальная ошибка стенда, не повторный auth/брутфорс. Пауза между логинами ≥60 с, fail2ban не сработал.
- Staging: 421 файл, 14 MB; `.env` и `local_database.db` — симлинки; `FILES 421`. У staging нет `.git`, поэтому `pins.git` в self-check = `ERR`; это ожидаемо, а 8 пинутых модулей совпали с локальными 8/8.
- `DB_MTIME`/размер до: `1792910955 / 1624113152`; после: `1792911855 / 1624240128` (+126 976 B). Это активность живого бота за 5 минут; harness открывает SQLite `mode=ro`, PG — read-only, прямых записей стенда нет.
- 16 новых ответов + 4 old-ответа; L1 2.8–4.4 с на прогон, L2 2.4–10.7 с; `invalid=0`, `fatal` нет, fallback/retry нет. Ошибки `mca_experience.list_lessons` — известный дефект стенда (`store=None`), `lessons_block` пуст, на Writer не влияет.

## 2. L1: 8 формулировок + forced

| Прогон | plan source | action / response_act | extent / structure | mode | predicate | attempts |
|---|---|---|---|---|---|---|
| new A | llm | reply / **answer** | compact / answer | casual | **false** | 1 |
| new B | llm | reply / **research** | normal / answer | serious | true | 1 |
| new C | llm | reply / emotional_reply | compact / chat | casual | false | 1 |
| new D | llm | reply / emotional_reply | compact / chat | casual | false | 1 |
| new E | llm | reply / **research** | detailed / report | deep_research | true | 1 |
| new F | llm | reply / historical_recall | normal / answer | casual | false | 1 |
| forced A | forced | reply / research | normal / answer | serious | true | — |
| forced B | forced | reply / research | normal / answer | serious | true | — |
| old A | llm | reply / answer | compact / chat | casual | false | 1 |
| old B | llm | reply / research | compact / summary | serious | false | 1 |

- **A/B natural: research 1/2.** A — `answer`, confidence 0.85, payload без analysis-блока; B — `research`, confidence 0.85, analysis 1×1. Forced A/B — 2/2 research.
- Канон: `code` 9588 симв., sha12 **`cc020660ae03`** во всех 8; PG прода 8261, `6c2ddc17c998`, `pg_matches_code=false` (ожидаемая преддеплойная ступень).
- E: `action=reply`, `response_act=research`, `extent=detailed`, `structure=report`, confidence 0.7 — **не silent**; ответ 2318/2952 симв., содержательный.
- F: `historical_recall`; ответ честный: «не было конфликта… если что-то серьёзное и было — я это пропустил, тут только подколы».

## 3. Payload: Core, analysis, no-meta, quote

| Прогон | system | user | Core | Core sha12 | offset | identity | analysis dir/writer | NO_META | QUOTE |
|---|---|---|---|---|---|---|---|---|---|
| new A/B/C/D/F | 14377–14409 | 5869–6872 | **3294** | **`ead77b2ab509`** | 3083 | 5048 | 1/1 (B); **0/0 (A,C,D,F)** | 1× | 1× (B) / 0 (A,C,D,F) |
| new E | 14829 | 6829 | **3294** | **`ead77b2ab509`** | 3083 | 5048 | 1/1 | 1× | 1× |
| forced A/B | 14406 | 6764/6859 | **3294** | **`ead77b2ab509`** | 3083 | 5048 | 1/1 | 1× | 1× |
| old A/B | 13866/13893 | 4965/5062 | — | — | — | 5048 | 0/0 | 0 | 0 |

- **Core:** слой ровно **3294** симв., sha12 **`ead77b2ab509`**, offset 3083 — во всех 6 new + 2 forced; в old Core 3294 нет. Это совпадает с ожидаемым.
- **Exact 1×/0:** по факту маршрута — research B/E/forced 1×1, casual C/D/F 0×0; A ошибочно попал в 0×0 из-за `answer`.
- **NO_META_STRUCTURE_TEXT:** ровно 1× в каждом new/forced payload, 0 в old. Модель директиву всё равно нарушает (см. §4).
- **QUOTE_FIDELITY_TEXT:** ровно 1× на research/deep payload, 0 на casual; модель правило не выполняет.
- `core` в raw-отчёте снова `chars=0` (известный дефект отчётности harness); проверка сделана по слою/system, не по `manifest.versions.core`.

## 4. Мета в первом предложении и структура

Строгий срез — первое предложение каждого из 16 new/forced ответов:

| Прогон | 1-й ответ | meta | 2-й ответ | meta |
|---|---|---|---|---|
| new A | «**Ну**, ты не злобный…» | **да** | «Ты не злобный — просто резко реагируешь…» | нет |
| new B | «Да не, не злобный он.» | нет | «Да хуй его знает, Макс.» | нет |
| new C | «Да не, норм.» | нет | «Да не, дождь норм.» | нет |
| new D | «Да нет, Макс, ты норм.» | нет | «Бля, Макс, ты реально хочешь честный ответ…» | нет |
| new E | «**Давай** без лишних церемоний.» | **да** | «**Окей, глянул** твою простыню.» | **да** |
| new F | «Судя по тому, что вижу в логе…» | нет | «Да не было никакого конфликта.» | нет |
| forced A | «Ты не злобный — просто у тебя ноль толерантности…» | нет | «Да не злобный ты…» | нет |
| forced B | «Не злобный — просто заебаный.» | нет | «Да не злобный он.» | нет |

- **Meta в первом предложении: 3/16** (A1, E1, E2); требование — **0**, поэтому **FAIL**.
- При сканировании всего первого абзаца по токенам — **5/16**: дополнительно C1 (цитата «давай завтра» внутри примера) и forced A2 («Ну серьёзно» во втором предложении, не анонс). Это ещё раз показывает: контракт не выполнен, но строгий счёт — 3/16.
- **Структура:** E2 содержит 5 нумерованных разделов + bullets; E просил «разбери подробно… с примерами», то есть структура запрошена. В B/C/D/F/forced нумерации нет. Отдельного FAIL за структуру нет.
- **Длины:** A 204/317, B 298/298, C 188/129, D 250/492, E 2318/2952, F 355/156, forced A 374/765, forced B 618/177.

## 5. RAG / FREQ / alias

- **RAG new/forced:** `rows=40`, `after_self_filter=40`, `after_dedup=39`, `kept=39`, cap 2000, block **2027** симв., sha12 **`1fdb8b237233`**; маркеры: **18** `(не подтверждено)`, **4** `(предположение)`, **22** `[чат]`, **0** `[Бот]`.
- **RAG old:** 40/40, legacy-рендер, block 2027, sha12 `e0d4f1db2b77`, 0 provenance-маркеров.
- **FREQ:** `frequent_text=true`; occasional/off=false; PG global/chat `profanity=frequent`, revision 2.
- **Alias:** uid `42115912` → **`Макс`** (`source=chat`, global тоже `Макс`), display `Гипербореец` — не алиас. Регрессии нет.

## 6. 9 проверок (§5–§6 probes_final2, P0 §1.1/§3)

| # | Проверка | Факт (цитаты) | Вердикт |
|---|---|---|---|
| 1 | Прямой ответ без метавступления | A1 «**Ну**, ты не злобный…»; E1 «**Давай** без лишних церемоний.»; E2 «**Окей, глянул** твою простыню.» — **3/16** | **FAIL** (требовалось 0) |
| 2 | Нет навязанной структуры/нумерации | Нумерация только E2 (5 разделов) при явной просьбе E «подробно… с примерами»; B/C/D/F/forced — без списков | PASS (E — по запросу) |
| 3 | Нет искусственной драматургии | 0 «однажды/кульминация/в далёком»; F «не было конфликта… если что-то серьёзное и было — я это пропустил» | PASS |
| 4 | Нет неподтверждённых дат/цитат | Дат/годов — 0. Кавычки: E **17 из 30** не являются точной подстрокой payload; примеры: «супермега хейт какой то… без причины -_- ☹️», «ой бля о5 старьё какоето… вот слушай русский свежачок», «чуствуется на коже» (в источнике «чувствуется»), «не нравитса» (в источнике «не нравится»). B 2/2, C 2/2, D 1/1, forced A 2/3, forced B 2/7 — тоже не точные | **FAIL** (по цитатам; даты чистые) |
| 5 | L2 не выдаёт интерпретацию за историю / self-echo | new: 0 `[Бот]`, 0 «я уже говорил»; F честно оговаривает предел 50 сообщений; old B — без нового self-echo в этом прогоне | PASS для new |
| 6 | FREQUENT — настоящий, без few-shot | `frequent_text=true`; PG global/chat `profanity=frequent`, rev 2; мат фактический, без механической вставки | PASS |
| 7 | Явный разбор — подробно | E **2318/2952** — PASS; A **204/317** без analysis-блока, B **298/298** — для явного разбора слишком коротко | **FAIL для A/B**; E PASS |
| 8 | Обычный вопрос — коротко | C **188/129**, D **250/492**; без эссе; D2 длиннее, но всё ещё бытовой ответ | PASS (D2 — с оговоркой) |
| 9 | Core и индивидуальность | Core **3294**, sha12 **`ead77b2ab509`**, identity 5048; old Core 3294 нет | PASS |

## 7. Находки

- **F1 OPEN (L1, блокер):** A natural = `reply/answer`, `compact`, predicate false, 204/317 симв. без analysis-директивы. Требование «A/B research 2/2» не выполнено — **1/2**. Это один сэмпл при temperature 0.7, но приёмочный критерий именно 2/2; prior `probes_final3` на `c0d5a3d3` давал A research.
- **F2 OPEN (no-meta, блокер):** 3/16 первых предложений с «Ну/Давай/Окей, глянул». Директива `NO_META_STRUCTURE_TEXT` ровно 1× в payload, но Writer её не выполняет. Требование 0 — FAIL.
- **F3 OPEN (quote-rule, блокер):** 26/45 кавычек new/forced не являются точной подстрокой payload; в E — 17/30. Это пересказы с многоточиями/орфографическими заменами, а не дословные цитаты; `QUOTE_FIDELITY_TEXT` 1× присутствует, но не соблюдается.
- **F4 (B, не отдельный блокер):** B — research 1×1, но 298/298 и `normal/answer`; «явный разбор подробно» для B не выполнен.
- **F5 (стенд):** `manifest.versions.core` = 0 при слое 3294; `list_lessons` traceback в new и old; SQLite вырос на 126 976 B за живой сеанс (бот), harness — `mode=ro`.
- **F6 (процесс):** 2 SSH-логина; первый — локальная ошибка пути до upload, 0 LLM-вызовов; прод не менялся.
- **PASS:** Core 3294/`ead77b2ab509`; canon code `cc020660ae03`; exact 1×1/0×0 по маршруту; E не silent и содержательный; RAG 40/39 + маркеры; FREQ; alias; отсутствие выдуманных дат; F честный.

## 8. Вердикт и дальше

- **FAILED**: закрыты Core, E, RAG/FREQ/alias, F, даты; **не закрыты** L1 A/B 2/2, no-meta 0, quote-rule. `VERIFIED` не заявляется.
- **Deploy не выполнять.** Прод остаётся **2.58.130 @ `534ac7dd`**; rollback не требуется (изменений на проде не было).
- **Builder:** F1 (маршрут A), F2 (первый абзац), F3 (кавычки только дословно/без кавычек при пересказе), F4 (длина B); затем повторный прогон тем же стендом.
- **Reviewer:** строки 1, 4, 7 держать FAILED; E/Core/RAG/FREQ/alias — PASS; process F6 — не блокер продукта.

## 9. Raw

`probes_final4/`: 10 raw (`raw_new_A/B/C/D/E/F`, `raw_forced_A/B`, `raw_old_A/B`), `selfcheck_new.json`, `ssh_session.json`, `harness_extra.py`, `manifest.json` (sha256 файлов). Секреты не выгружались; alias — только uid `42115912` и `Макс`.
