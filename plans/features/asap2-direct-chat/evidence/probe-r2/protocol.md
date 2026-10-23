# ASAP2-PROBE-R2 — протокол остаточной семантической пробы Direct Chat (§6)

**Лейн:** ASAP2-PROBE-R2. **Дата прогонов:** 23.10.2026, ~05:35–05:50 (+12:00).
**Кандидат:** `e4ee54f3` (release 2.58.113, деплой-кандидат). Worktree
`C:\Code\Python\adminbot-wt-asap2probe` создан от него; основной чекаут не
трогался.

Проверяемый код Direct Chat байт-в-байт совпадает с ревьюированным `34af90ff`:

```text
git diff --stat 34af90ff e4ee54f3 -- services/direct_l1.py \
    services/direct_chat_service.py services/chat_prompts.py   -> пусто
```

Различия `services/` между этими коммитами (`database.py`,
`embedding_control_plane.py`, `graphrag_rebuild.py`, `llm_client.py`,
`pipeline_events.py`, `summary_l2_*`, `summary_memory.py`) к Direct Chat
отношения не имеют. Код в этом лейне **не менялся** — дефектов не найдено.

## 1. Изоляция

- Ноль соединений с прод-БД/PG, Telegram, SSH, живыми чатами. `.env` основного
  чекаута только читался (`dotenv.load_dotenv(<abs path>)`), ничего не писалось.
- Контекст L1 собирает **боевая** `direct_l1.build_l1_context`; `<Current_Question>`,
  reply-блок и speech-hints — **боевые** методы
  `DirectChatService._render_current_question`, `._l1_reply_block`,
  `_strip_direct_prefix`/`_message_user_text` (media-маркеры reply/own
  включены, `NATIVE_REPLY_MEDIA_CONTEXT_ENABLED` default ON).
- L2 — боевой `compose_verbalizer_system` (канон + mode/extent-блок) и боевой
  `direct_l1.build_l2_plan_block`; `rejected`-пометка считается боевым
  `direct_capabilities.resolve_capabilities` (как `_l1_tool_subset`).
- Транспорт: ровно один POST на вызов, без скрытого retry-каскада, без
  fallback-модели. Транспортный обрыв до отправки в ledger не попадает
  (в этом прогоне их не было).

## 2. Модель и sampling

| Параметр | L1 planner | L2 writer |
|---|---|---|
| модель (запрошена/ответила) | `deepseek/deepseek-v4.1-flash` (nano-gpt.com) | та же |
| temperature | не передаётся (`l1_temperature(None)` → None) | `0.7` (`settings.tone_temperature(None)`) |
| max_tokens | `512` | не передаётся |
| system (sha256[:12], длина) | `c987c03e3ee0`, 6542 симв. (все 14 L1-вызовов) | 2941–3338 симв., sha зависит от mode/extent-блока |
| finish_reason | `stop` во всех вызовах | `stop` во всех |

Важно для честности: предыдущий лейн `ASAP2-PROBE` гонял `deepseek-v4-flash`
(apinet.cloud). Здесь — модель прода по заданию (`deepseek/deepseek-v4.1-flash`,
nano-gpt), поэтому результаты не «повторный прогон того же», а независимая
выборка на актуальной модели. `model_requested == model_returned` во всех 17
сохранённых raw.

## 3. Бюджет: 19 из 20 платных вызовов

| Группа | Вызовы |
|---|---|
| L1 сценариев и парафраз | 14 |
| L2 текстов (T10, T18b, T22, T26, P-OBJ1) | 5 |
| bounded repair (`finish_reason=length` / невалидный JSON) | 0 |
| **Итого** | **19** (1 неиспользован) |

Ledger построчно (`n`, label, ts, HTTP status): `ledger.jsonl`, все 19 — HTTP 200.
Две строки помечены одинаковыми label (`L1 T10`, `L1 T10a`): первый прогон этих
двух сценариев шёл с объявленным `chat_history` и дал tool-маршрут; для проверки
именно «ответ из видимой части» набор возможностей сужен и сценарии
перезапущены (raw перезаписан, план первого прогона зафиксирован в
`results.md` §5). Счётчик бюджета append-only, поэтому обе пары видны.

## 4. Состав L2-контента (ограничение методики)

User-часть L2 = план-блок + `<Recent_Messages>` (окно) + `<Current_Question>`,
как в прошлом лейне. В проде туда же идут персона/стиль/память/lessons и
tool-evidence. Здесь tool-маршруты **не исполнялись** (нельзя подсовывать
выдуманный tool-evidence) — исходы T11/T14/T17 фиксируются на уровне плана
(`tool_use`), это ровно проверяемый контракт «не спрашивает повторно, а идёт
делать». Для T10 план содержал `user_memory`; сам инструмент не запускался,
L2-текст строился по видимому окну — это отмечено в `results.md` §5.

## 5. Воспроизведение

```powershell
cd C:\Code\Python\adminbot-wt-asap2probe
$env:PYTHONIOENCODING='utf-8'
py -3 plans\features\asap2-direct-chat\evidence\probe-r2\probe_r2.py show T14,T22   # 0 вызовов
py -3 plans\features\asap2-direct-chat\evidence\probe-r2\probe_r2.py l1 T10,T11
py -3 plans\features\asap2-direct-chat\evidence\probe-r2\probe_r2.py l2 T10,T22
```

`BUDGET = 20`, `assert n < BUDGET` до отправки — бюджет нельзя превысить
незаметно. Raw: `raw/raw-*.json` (план + контекст для L1, текст + system/user
для L2).
