# LIVE-SCENARIOS §12-r2 — release 2.58.133 (deployed `b5716022`)

**Назначение:** re-probe неудачного набора r1 (S03/S05/S07/S10) + S02 + S04 на прод-коде 2.58.133 после micro-fix `eaabb66f` (LORE-VERBATIM-GATE). **Закрывает FAILED-критерий §12** «lore story не подменяет analysis-ответ» из `live-scenarios.md`.
**Дата прогона:** 26.10.2026 13:53–14:02 UTC (27.10 UTC+12). **Контур:** идентичен r1 — read-only (SQLite-снапшот-копия 1562 MB через `sqlite3 backup`, прод не тронут; PG `default_transaction_read_only=on`, probe `ro_ok:ReadOnlySQLTransactionError`), реальный LLM (`deepseek/deepseek-v4.1-flash`, hot-конфиг из PG, `wide_context_hot=true`), **ноль Telegram** (FakeBot), реальный `_handle_turn`, чат `-1004482340693`.
**Стейджинг:** `/tmp/p0d` из deployed SHA `b5716022` (`git archive`; sha256_12 пинов `settings.py ec489d05564e`, `direct_chat_service.py a3dc914c6cd3`, `tool_router.py fe25ca5898dd`, `direct_l1.py ff7e9c9713e8` == deployed). **Драйвер:** `live_scenarios_12.py` **байт-в-байт r1** (sha256 `ca500edb357bd3f7077bf236e13fbb46f417eaff910674c64f5330843ea4a96b`, проверен на сервере до и после); обёртка `rerun_r2.py` (sha256 `73256c69…`) только выбирает 6 сценариев из `build_scenarios`, пишет в отдельный `results-r2/` и дозаписывает `ctx_flags` (`lore_verbatim_instruction`, маркер `СИСТЕМНАЯ ИНСТРУКЦИЯ` по всем tool-`result_raw`, полный текст story для offline-similarity). Файл драйвера не изменялся.

## Критерии приёмки лейна (DEPLOY-258133, PART 3)

- S03/S05/S07/S10: ответ **Writer-композиция** (не verbatim-story; similarity низкая), story остаётся provenance-материалом тул-результата, verbatim-return инструкции в payload **нет**.
- S02: честный отказ/ограничение по неразрешимому субъекту сохранён.
- S04: story-путь не сужен (инструкция присутствует на genuine story-интенте, нарративный ответ).
- Без выдуманных дат/цитат/источников; композиции могут различаться между сценариями (не дефект).

## Результаты по сценариям

| # | L1 план (act/structure) | Lore gate | ctx verbatim-флаг | Инструкция в payload | Story в ответе (sim / max-contig-слов) | `story_delivered_as_reply` | Ответ | Вердикт |
|---|---|---|---|---|---|---|---|---|
| S02 uid-сообщения | research/report | False | **False** | **нет** (0 тулов) | sim 0.014 / 5 | false | 1061 зн., честное ограничение «полного архива нет» + реальная выборка | **PASS** — честный отказ сохранён |
| S03 период 2022–2026 | research/report/detailed | False | **False** | **нет** | sim 0.017 / 1 | false | 125 зн. (см. Находку 1) | **PASS** (D1) — story не подменяет; см. Находку 1 |
| S04 мем-история | research/**story**/normal | False | **False** | **нет** | sim 0.008 / 3 | false | 792 зн., нарратив-ответ «мема нет, вот что реально нашлось» | **PASS с примечанием** (см. Находку 2) |
| S05 мета-эссе | research/report/detailed | False | **False** | **нет** | sim 0.018 / 9 | false | 4304 зн., развёрнутое эссе с честной оговоркой об охвате | **PASS** |
| S07 пара (отношения) | research/answer/normal | False | **False** | **нет** | sim 0.015 / 6 | false | 600 зн., composed разбор по видимым кускам | **PASS** |
| S10 период 2018–2029 | clarification/chat/compact | False | **False** | **нет** | sim 0.072 / 4 | false | 551 зн., честный отказ «архив 8–26.10.2026» без выдуманных лет | **PASS** |

Сводное: 6/6 сценариев — `lore_verbatim_instruction=False`, инструкция `[СИСТЕМНАЯ ИНСТРУКЦИЯ: …]` **не найдена ни в одном tool-payload** (скан `result_raw` всех вызовов), `story_delivered_as_reply=false` везде, similarity ответ↔story 0.008–0.072 (порог композиции), ошибок сценариев нет (dur 49–73 c). Story при этом собран и остаётся материалом: `ctx_lore_compiled=true`, `ctx_story_len` 1714–2602, журнал `[direct] lore story kept as evidence (non-story intent)`; `compile_lore_story`/`dig_into_lore` в фиксе не менялись (0 строк), provenance-поля — unit payload-контролы. Выдуманных дат/цитат/источников не обнаружено (S10 честно называет границы архива).

## Закрытие FAILED-критерия §12

**«Lore story не подменяет analysis-ответ» — ЗАКРЫТ (PASS).** На всех четырёх ранее падавших сценариях (S03/S05/S07/S10) verbatim-инструкция больше не попадает в payload на research-интентах, готовая story не доставляется как ответ, ответы компонует Writer; гейт доставки при этом остаётся честным `False`. Причина дефекта r1 (дефолт `ToolContext.lore_verbatim_instruction=True` на любом интенте) устранена wiring-фиксом `eaabb66f`: инструкция ⇔ `lore_story_delivery_allowed` через `lore_verbatim_allowed(l1_plan, response_plan)` + kill-switch `LORE_STORY_INTENT_GATE_ENABLED`.

## Находки

**1. Инцидентальное (качество Writer, не блокер D1):** S03 ответил coverage-стабом 125 зн. («сообщений с совпадением: 3888; метод: совпадение по префиксу…; полнота: полная») вместо развёрнутого анализа. Это не verbatim-story и не выдуманные данные (числа реальные, из тул-результата); композиции Writer варьируются (S05 — 4304 зн.). Отдельное наблюдение для Builder/Reviewer вне рамки D1; на r1 этот сценарий падал сильнее (ответ = story).

**2. S04 — примечание по «инструкция присутствует»:** L1 снова (как и в r1) классифицировал запрос как `research/story` → analysis-акт побеждает в гейте → `delivery_allowed=False` → инструкция отсутствует **по iff-контракту фикса** (инструкция ⇔ гейт): живое поведение консистентно, narративный ответ составлен, verbatim нет ни в какую сторону. LIVE-проверка TRUE-стороны (genuine story-интент) в этом прогоне не выпала — ни один сценарий не получил story-классификации L1 (в r1 — тоже); TRUE-сторона доказана контракт/payload-юнитами `test_p0_delta_routing.TestLoreVerbatimInstructionGate` (12 тестов, включая story-контролы S04/S09 «инструкция на месте» на реальном dispatch `compile_lore_story` с ctx как в call-site; 111 passed на кандидате). Механизм TRUE-стороны не менялся фиксом.

**3. Стейджинг-only (не прод):** traceback `usage_events` INSERT → `ReadOnlySQLTransactionError` — ожидаемое следствие read-only PG-контура (probe `ro_ok`); после `DONE` процесс держался в shutdown на фоновых задачах FACTS_EXTRACT (read-only записи отклонены) — процесс убран, прод не затронут (unit active, NRestarts 0, healthz 200 перепроверены).

## Raw-файлы и sha256

Scratch: `OPENCODE_WORKFLOW_SCRATCH/deploy-258133/r2-results/` (server: `/tmp/p0d/results-r2/`, `/tmp/p0d/run_r2.log`).

```
c4c94fef85abe439acecca3d42c44b0fb98041c2145b6f6301ef6f6ee3638e5c  boot.json
e762cb1d9f22bd40344d899d5f52db90b36929778abc3c981c8124982116656d  summary.json
d331b1e4659fe81594e3b5b630b0d4376fa2e951a82e0d15883238b3dfc576c9  S02_uid_messages.json
ade18e4b7d96c0583324d1379ebce679e2e6417fa9b22854d299ed6585c38f83  S03_period_change.json
64e57d3511a1fd161f230b23f4aafa3e3229c9c38be4c17ee288c602b7961c9a  S04_meme_story.json
bbfe1c2d275354a37cf46dcadcd7a1dde584db70b44edaed1eb6ded5c31d5839  S05_meta_essay.json
7215b11f62203f2627b864947afe0ce0805f5a843112cdbde07575ec68bb773a  S07_ambiguous_pair.json
384882ab2c3697b5861b6b7be007aa68bc59610e6204ea4c021d6ca70948a369  S10_long_period_coverage.json
d36fedb4a0187d433ed75294e49cda97d4192940faf48608a2b94e84193e7d25  run_r2.log
ca500edb357bd3f7077bf236e13fbb46f417eaff910674c64f5330843ea4a96b  live_scenarios_12.py (driver, байт-в-байт r1)
73256c692f8ed5e0d1b202c8a6082944de72e17d59746beca585fb8dea3f5a48  rerun_r2.py (обёртка выборки/ctx_flags)
```

**Вердикт §12-r2:** все критерии лейна выполнены; FAILED-критерий r1 закрыт. Прод 2.58.133 (`b5716022`) работоспособен (healthz 200 loopback+внешний, NRestarts 0, журнал чист).
