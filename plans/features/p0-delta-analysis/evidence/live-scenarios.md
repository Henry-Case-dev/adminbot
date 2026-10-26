# LIVE-SCENARIOS §12 — release 2.58.132 (deployed `d3a9a2cc`)

**Дата прогона:** 26.10.2026 12:42–12:50 (серверное UTC+12). **Контур:** read-only (SQLite-снапшот-копия 1.6 GB через `sqlite3 backup`, PG `default_transaction_read_only=on`, probe `ro_ok`), реальный LLM (`deepseek/deepseek-v4.1-flash`, hot-ключ из прод-PG), **без Telegram** (FakeBot). Драйвер: полный продовый `_handle_turn` на реальном чате `-1004482340693`, инструментальные записи через monkeypatch (dispatch/_l2_write_answer/normalize_l1_plan) — прод-код не изменялся.
**Драйвер:** `live_scenarios_12.py` sha256 `ca500edb357bd3f7077bf236e13fbb46f417eaff910674c64f5330843ea4a96b` (scratch: `p0d-258132-live-scenarios/analysis_texts.txt` — выдержки; raws — 12 JSON, sha256-список ниже).
**Данные:** чат 2022–2026, топ-авторы из БД (Леха и др.); сценарии 3/8/10 построены на реальных годах из БД.

## Таблица сценариев

| # | Сценарий | L1 план (act/structure/extent) | Тулы | Coverage | Lore gate | Верdict |
|---|---|---|---|---|---|---|
| S01 | атмосфера/отношения | research/answer/compact | get_recent_history (timeout 10 c) + query_chat_memory | — | **False** (research) | **PASS** — analysis-роутинг, история не подменила, честно про обрезанную историю |
| S02 | сообщения участника по uid | research/report/compact | get_recent_history + dig_into_lore (3069/15) + compile_lore_story | total=3069, shown=15, top_by_relevance | **False**, story 2121 не отправлена | **PASS** — честный отказ/частичность: «953 совпадения по префиксу — это циферки, не смысл»; identity-путь (query_chat_memory person/uid) LLM не выбрал — контрактно покрыт тестами, live не exercises (заметка) |
| S03 | изменение за период (2022–2026) | research/summary/normal | get_recent_history + dig_into_lore (3878/15) + compile_lore_story | total=3878 | **False**, story 2470 | **FAIL (критерий lore)** — ответ ≈ story (Δ2 символа): story заменила analysis-ответ; период фильтруется (totals по сценариям различны: 3069/3878/2343/4160), честная оговорка про покрытие есть |
| S04 | локальный мем | research/story/normal | get_recent_history + query_chat_memory | — | **False** | **PASS** — нарратив из памяти, честная оговорка про таймаут глубокой выборки; story не компилировалась |
| S05 | детальное мета-эссе | research/report/detailed | 5 тулов incl. get_user_context (person resolved) + dig (2343/15) + compile_lore_story | total=2343 | **False**, story 2233 | **FAIL (критерий lore)** — ответ == story **дословно** (2233/2233, `story_delivered_as_reply=true`) при research-плане |
| S06 | бытовая короткая фраза | answer/chat/**micro**, tools=**none** | нет | — | True (fail-open, нет story) | **PASS** — 89 символов, 1 абзац |
| S07 | двусмысленные отношения пары (реальные имена) | research/answer/compact | get_recent_history + query_chat_memory + dig (3721/15) + compile_lore_story | total=3721 | **False**, story 2311 | **FAIL (критерий lore)** — ответ ≈ story (Δ5 символов) |
| S08 | точная статистика (2022) | research/report/normal | get_recent_history only | — | **False** | **PASS** — честный отказ («инструмента для подсчёта нет»), ноль выдуманных чисел; заметка: stats-тул LLM не попытался |
| S09 | креатив | **creative**/story/normal, tools=none | нет | — | **True** (creative разрешён) | **PASS** — полноценный рассказ 1542 симв. |
| S10 | период больше истории (2018–2029) | research/report/detailed | get_recent_history (timeout) + query_chat_memory + dig (4160/15) + compile_lore_story | total=4160 | **False**, story 2250 | **FAIL (критерий lore)** — ответ == story дословно (2250/2250, `story_delivered_as_reply=true`); при этом сам текст честно о покрытии («с 2018 по 2029 в данных толком не расписан… октябрь 2026») |

**Прочие критерии:** роутинг различается по интентам (tools=none на S06/S09; разные наборы тулов) — PASS; анти-шаблонность (длины/композиции ответов: 569/2208/2468/863/2233/89/2306/440/1542/2250) — PASS; период в SQL — подтверждён косвенно (различие coverage totals по периодам; явных year_from/year_to аргументов LLM в live не передавал — dig извлекает годы из query); выдуманные даты/цитаты — не обнаружены (даты в ответах соответствуют данным: «8 октября 2026», «с 2026-10-08» из evidence).

## Находка (маршрут Builder → Reviewer)

**«Lore story подменяет analysis-ответ» — дефект дельты устранён не полностью.**
Детерминистический гейт доставки (`lore_story_override` → `""` для analysis, лог «lore story kept as evidence») **работает** — прямой подмены через override нет. Но финальный ответ на research-сценариях с успешным `compile_lore_story` — это сама story:

- **Механизм:** тул-результат `compile_lore_story` содержит мягкую инструкцию `_LORE_RETURN_INSTRUCTION` («верни пользователю текст из поля story ДОСЛОВНО…») при `ctx.lore_verbatim_instruction=True` (дефолт Direct-хода, `tool_router.py`, S10.20-4). Инструкция попадает в evidence-пак → Writer (L2) повторяет story дословно/почти дословно (S03 Δ2, S05 Δ0, S07 Δ5, S10 Δ0). На деградированных путях (get_recent_history timeout → tool-loop degraded) ту же роль играет финальный текст инлайн-модели tool-loop.
- **Соответствие контракту:** impl.md дельты: «история остаётся материалом в evidence (тул-результат с provenance уже в пакете), отвечает Writer» —.Writer обязан компоновать analysis-ответ, а не ретранслировать story. Наблюдаемое — подмена ответа (§12: «lore story does NOT replace analysis answers»).
- **Воспроизведение:** S05 (research/report): ответ == ctx.lore_story побайтно; S10 — то же; S03/S07 — Δ2/Δ5 символов.
- **Предлагаемый минимальный фикс (Builder):** при нелегаси-плане с `lore_story_delivery_allowed=false` исключать `_LORE_RETURN_INSTRUCTION` из тул-payload (например, `ctx.lore_verbatim_instruction=False` ставится в точке создания ctx, когда гейт блочит, либо инструкция вырезается при сборке evidence для analysis-планов) + контракт-тест «evidence для research-плана не содержит verbatim-инструкцию story». После фикса — точечный повтор S02/S03/S05/S07/S10 и релиз 2.58.133.

**Заметки (не блокируют):** (1) LLM в live не вызывал `query_chat_memory` с явным person/uid (S02) и не передавал year-аргументы явно — identity/period-пути покрыты контрак-тестами (1110+152), live-упражнение через LLM-роутинг недетерминированно; (2) stats-тул на S08 не попытан — ответ честный, «разделение stats/search» по факту соблюдено (числа не выдуманы); (3) `get_recent_history` timeout 10 c на 2 сценариях (S01/S10) — штатный degradation; (4) graphrag «own=0/20, filtered_other_chat=512» — чат-скоуп KNN сильно фильтрует чужие чаты (pre-existing, отдельная наблюдаемая, не из этой дельты).

## Raw-файлы и sha256

Scratch: `OPENCODE_WORKFLOW_SCRATCH/p0d-258132-live-scenarios/` (main repo), сервер: `/tmp/p0d/results/`, `/tmp/p0d/run3.log`.

```
6d20102b0c8949113dc0a8c7c6b56ec8602a3e4fb9d676b1c6d09fe612cd3705  boot.json
7431ec6e432f1c06ab1d41a6285679399ab1384befae0ee0548d32e2a1b541ac  S01_atmosphere_relations.json
ab0a9bef5d8e20ff530974321c3a996a31c0b7b48fd8be3e14f766db5584a7c9  S02_uid_messages.json
91ba3cb8aacd603681f37186a9f635a3dd4685f13b1c885aed2917729325bbe4  S03_period_change.json
12a16c1a1414f34b04a1a9da45554440281c297b6a331226bbdfbad5870d2faa  S04_meme_story.json
07109833e8a3933d903443fe11fa15b2c7246fec4eb0b801396b012516ccda4d  S05_meta_essay.json
1d09d718d480f328677e2c4e2226c745eff70e2e7c1920e3103a2771eee6509a  S06_short_everyday.json
1026d6bd80d3a5914def72f402687a7dea3590a813c2674242c009618db39698  S07_ambiguous_pair.json
93f7bf8900289916e59f1fcc186efea540f6d0455e219f11e61bcefcfe060331  S08_exact_stats.json
4ee9ab93d70cffa476e8693eb4e67ad593b221379ccd52fd95d1a1ff927c4387  S09_creative.json
202146159dd05a1b29f17b0ecbf38f0cd269d3923f90585e5f04551cfe74ae31  S10_long_period_coverage.json
5bafa2c31c9d1d8389e6deb47d2cf68f6e3b409c421606ed9424c827f1177ea4  summary.json
ca500edb357bd3f7077bf236e13fbb46f417eaff910674c64f5330843ea4a96b  live_scenarios_12.py (driver)
```

**Вердикт §12:** 8/10 сценариев PASS, 4 подмены story на research-сценариях (S03/S05/S07/S10) → обязательный критерий не выполнен → **FAILED** для live-приёмки дельты; прод-деплой технически верифицирован (deploy.md), откат не требуется.
