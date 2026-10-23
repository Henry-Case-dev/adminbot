# SPEECH-HARNESS-R2 — протокол (методика, изоляция, бюджет)

**Лейн:** SPEECH-HARNESS-R2 (leaf writer, evidence + durable tests).
**Дата:** 23.10.2026, +12:00.
**Кандидат:** `e4ee54f3` (release 2.58.113, деплой-кандидат) — отдельный
worktree `C:\Code\Python\adminbot-wt-speech`; основной чекаут не изменялся.
**Код не менялся** (только новые тесты); найденные поведенческие дефекты
описаны в `results.md §7`, не «исправлены» подгонкой тестов.

## 1. Harness и изоляция

Метод ADTR-HARNESS-R1 / W3 (адаптация `OPENCODE_WORKFLOW_SCRATCH/r2/`):
`hbase2.py` + `run_all.py` + `run_tail.py`.

- **Реальные provider-вызовы** через боевой код `DirectChatService`
  (`_l1` planner → `_l2_write_answer`), боевые байты промптов кандидата.
- **Доставка перехвачена**: FakeBot (`send_message`/`send_chat_action`/
  `set_message_reaction`) + spy на `services.telegram_send.send_text` —
  ни одного сетевого вызова Telegram.
- **Прод-конфиг недостижим**: `POSTGRES_DSN` — мёртвый порт 9 → config
  cache в in-memory defaults; SQLite — scratch на процесс
  (`OPENCODE_WORKFLOW_SCRATCH/r2/db/`).
- Embeddings: заглушка `llm.embed` стояла, но путь `embed_once` её обошёл —
  17 embedding-запросов ушли провайдеру; их исход harness не захватил, в
  ledger они помечены «treat as billable» (protocol §4).
- `flags.unified_composer_enabled=1`, `character.core.detail_level=full`,
  `bot_self_awareness_enabled=false`, `chat_running_summary_enabled=false`
  (прецедент W3: фоновые пост-отправочные процессы вне речевого пути).
  Для tail-прогона дополнительно `GRAPH_RAG_ENABLED=False` — пост-
  отправочный ETL-экстрактор триплетов (фоновый memory-процесс), иначе
  каждый ход стоил +1 provider-вызов.
- Скрипты — untracked scratch, в evidence не входят.

## 2. Модель и sampling

`.env` dev-машины (скопирован в worktree; значения не коммитятся):
`LLM_BASE_URL=https://nano-gpt.com/api/v1`, модель
`deepseek/deepseek-v4.1-flash` — **та же модель, что у прода** по
указанию брифа (локальный `.env` переведён на nano-gpt).

| Ступень | temperature (факт payload) | max_tokens | system sha12 |
|---|---|---|---|
| L1 planner (direct + initiative) | ключ отсутствует (provider default) | 512 | `c987c03e3ee0` (все ходы) |
| L2 writer | 0.7 | None (auto) / 4096 при longform-плане | зависит от чата/плана |

Модель и temperature между режимами не менялись. `max_tokens` L2 —
следствие extent-плана L1 (не настройка harness); в serious-стимуле
off-прогон получил extent «подробно» → 4096. Зафиксировано как
ограничение сравнения (results §2).

## 3. Режим Expression (override + restore)

Перед каждым набором — `character.expression = {"profanity": <mode>}`
в in-memory кэше harness; снимок боевого резолва (`resolve_expression_settings`)
фиксировался в `expression_pre` каждого прогона:

| mode | source | text sha12 | marker |
|---|---|---|---|
| off | global | `76864fcb9ec3` | «Не используй мат в собственной речи.» |
| occasional | global | `c1d830356208` | «…с примесью мата» |
| frequent | global | `163ec217fc6a` | «…с выраженным использованием мата» |

После прогонов документ снят (`restore_mode_doc`); прод-конфиг не
читался и не писался.

## 4. Бюджет и ledger

**40 chat-completion вызовов** (лимит 40) + **17 запросов `/embeddings`**.
Полный построчный ledger: `ledger.jsonl` (57 записей, поле
`billable_completion`).

Честная оговорка: офлайн-заглушка `llm.embed` не покрыла путь
`embed_once`, поэтому 17 embedding-запросов реально ушли в провайдера
(`EMBEDDING_BASE_URL`/ключ заданы в `.env`); их HTTP-исход harness не
захватил — в ledger они помечены «treat as billable». Итог: лимит по
**completion**-вызовам соблюдён (40/40), по любым провайдер-запросам
фактически 57. Это ограничение бюджета лейна, не скрытая экономия:
речевые прогоны не урезаны задним числом, а embedding-вызовы —
побочные (память/ассоциации) и не входят в оцениваемый речевой путь.

| Фаза | Ходов | Chat-completions | embeddings |
|---|---:|---:|---:|
| I-матрица (8 сценариев) | 8 | 13 | 0 |
| EVAL-MODES (3 режима × 2 жанра) | 6 | 18 | 11 |
| s7 quoted (occasional) | 1 | 3 | 6 |
| P0D (off + мат в user input) | 1 | 2 | 0 |
| wit/sharpness (occasional) | 2 | 4 | 0 |
| **Итого** | **18** | **40** | **17** |

Сокращение выборки относительно §9.2 (3 режима × 3 жанра × 10 стимулов =
90 ходов, ≳270 вызовов) зафиксировано честно: 2 жанра на режим
(smalltalk + serious), 8 инициативных сценариев, 1 цитатный зонд,
2 стимула на остроумие. Причина — жёсткий лимит ≤40.

## 5. Границы доказательства

- Telegram-транспорт не задействован: «доставлено» = байт-равенство на
  шве `send_text`/FakeBot. Реакция — вызов `set_message_reaction` у FakeBot.
- Живые чаты владельца и прод не затрагивались (SSH/деплой не выполнялись).
- L1-решения — стохастические: фиксируется ФАКТ плана, а не «правильный
  ответ»; соответствие столбцу «приемлемое модельное решение» §7 судится
  по факту.
- `raw == sent` проверено разбором возврата `_l2_write_answer` (tuple
  `(text, mode)`); постпроцессоры/egress не изменили ни одного из 7
  проверенных текстов (results §3–§5).
