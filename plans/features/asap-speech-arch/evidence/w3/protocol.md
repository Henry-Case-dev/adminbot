# W3 Protocol — реальные сообщения (§9.2 source-снапшота 22.10)

**Лейн:** ASAP-W3-REALMSGS. **Дата прогонов:** 23.10.2026, 01:47–02:57 (+12:00).
**Код:** HEAD ec359bb3 (байты прода 2.58.111 @ fbf9013d; каноны W1 + активная миграция W2). Параллельный WIP ASAP-2 в services/ начался в 03:03:26 — после старта последнего прогона (03:01:03, импорты на старте процесса): все прогоны на одном коде.
**Harness:** `OPENCODE_WORKFLOW_SCRATCH/asap-w3/` (hbase.py + run_mode.py), метод ADTR-HARNESS-R1: реальные LLM-вызовы, FakeBot/telegram_send-spy на serialization-шве, мёртвый DSN (прод-конфиг недостижим), scratch-SQLite на режим.

## 1. Изоляция и restore (прецедент директивы)

Override `character.expression` = временный in-memory документ harness-кэша (ровно один явный контроль `profanity`, остальные inherit→фабрика). **Прод-конфиг не читался и не писался** (PG офлайн; ни одного соединения с продом). Restore после каждого набора: документ снят → боевой резолв вернулся к фабрике (mode=occasional, source=default) — `restore_ok=True` во всех 4 прогонах (в raw-*.json: expression_after_restore).

Дополнительно зафиксировано перед каждым набором (`PROBE-PRE` в логах + `expression_pre` в JSON): effective mode, source, sha12 текста Expression, маркер инструкции. Значения: off=76864fcb9ec3, occasional=c1d830356208, frequent=163ec217fc6a.

## 2. Модель и sampling (не менялись между режимами)

- Модель: `deepseek-v4-flash` (апнет; dev-.env — та же модель, что играли предыдущие harness-прогоны; W0-журнал прода показывал apinet-слот deepseek — байт-код канонов одинаков, модель фиксируется здесь честно).
- L1 planner: system f8ab20121c02 (канон W1), max_output_tokens=512, temperature=provider-default — одинаково во всех режимах.
- L2 writer: temperature=0.7 — одинаково во всех режимах; system собирается единым композером (Core full §3.2 fac:2ab417d11404 + Expression + канон §3.1 be03964322aa; режим-блок serious; style_policy/few_shot отсутствуют в harness-конфиге — source_missing, одинаково во всех режимах).
- Хэши effective prompt: system-sha12 каждого вызова в raw-*.json (llm_calls[].system_sha12); полные messages-sha12 там же. Кросс-режимные различия system на тех же стимулах = ровно ветка Expression (analysis.md §2).

## 3. Выборка и бюджет (фиксация уменьшения)

План §9.2: 3 режима × 3 жанра × 10 стимулов = 90 ходов. Бюджет лейна ≤45 provider-вызовов. Фактическая цена хода (L1 + L2 + фоновые механизмы памяти, вне речевого пути) = 3–5 вызовов → полный план требует ≳270 вызовов. **Уменьшение зафиксировано**: 5 стимулов-микс (болтовня ×2, фактический ×1, serious ×1, инициатива ×1) × 3 режима + off-пилот s3. s7 (цитатный зонд) не выполнен.

Ledger вызовов (итого 45 = лимит):

| Прогон | Вызовы | Что потеряно |
|---|---|---|
| off pilot | 16 | s4 raw (ответ salvажен из БД) |
| off addendum попытка-2 | 3 | ответ s5 попытки (crash saver) |
| off addendum попытка-3 | 4 | — (salvage в raw-off-addendum.json) |
| occasional core | 12 | s6 (кап) |
| frequent core | 10 | s4 (кап) |

Ошибки ранних попыток (UNIQUE-конфликт сида при переиспользовании БД; NameError SET_NAME при сохранении; tuple-repr в захвате raw) исправлены в раннере; на итоговые данные не влияют (все сохранённые ответы проверены).

## 4. Логи прогонов

Полные stdout прогонов: `OPENCODE_WORKFLOW_SCRATCH/asap-w3/{off-add,occ,freq}.log` (BOOT/PROBE-PRE/TURN/BUDGET/PROBE-POST; embed-401 зонды — офлайн-отказ embeddings, в бюджет речевых вызовов не входят). Raw-ответы (полные тексты, llm-мета, логи ходов, intent-row): `raw-off-pilot.json`, `raw-off-addendum.json`, `raw-occasional.json`, `raw-frequent.json` в этом каталоге.

## 5. Регрессия summary/factcheck (0 платных) — метод

```
.venv\Scripts\python.exe -m pytest tests/test_asap_w1_semantics.py \
  tests/test_summary_asap21_prompt_migrations.py tests/test_prompt_migrations.py \
  tests/test_factcheck_prompts.py tests/test_summary_prompts.py \
  tests/test_outgoing_guard_round1022.py -q
```

- На detached worktree HEAD (4b4146c7): **142 passed / 0 failed**.
- В общем рабочем дереве: 133 passed / 9 failed — все 9 в test_prompt_migrations (лестницы verbalizer/L1) из-за НЕЗакоммиченного WIP параллельного лейна ASAP-2 (добавляет ступени PREV_CHAT_VERBALIZER_W1_31 / PREV_DIRECT_L1_PLANNER_W1; старые assert-ы списков ступеней падают). Классификация: unrelated/parallel-WIP, не регрессия W3 (мой лейн код не менял; на HEAD зелёный). 2 initial fails (outgoing_guard ImportError aiogram) — артефакт глобального интерпретатора (aiogram 3.29.1 вместо venv 3.31.0); под venv зелёные.

## 6. Границы доказательства

- Telegram-транспорт не задействован: serialization-шов (FakeBot/telegram_send-spy) фиксирует текст, передаваемый transport-уровню; «доходит до отправки» = байт-равенство на этом шве.
- Живые чаты владельца — отдельная (необязательная) зона наблюдения по standing rule проекта; инженерное доказательство замкнуто офлайн-harness-ом на боевых байтах.
- Инициативный текст: L1 в обоих выполненных режимах не выбрала reply (silent/react) — машинное решение участия; режим-голос инициативного L2-текста не снят.
- occasional: 0/4 с матом — в пределах инварианта §3.4; частотного различия off↔occasional выборка не показала (показала frequent↔{off, occasional}).
