# EVOL-REPLY-CONTEXT-INTEGRITY-01 — production case trace (read-only)

Статус: **case located and reconstructed from live production data**. Кейс реален, не гипотетический.
Ветка потери смысла подтверждена кодом задеплоенной ревизии.

- Дата наблюдения: **2026-11-06**, 16:45:46–16:45:49 UTC (сообщения чата — UTC, epoch из Telegram).
- Прод: `2.58.161`, deployed commit **`a563ee31`** (подтверждён `/healthz` → `{"status":"ok","version":"2.58.161"}` и файлом ревизии).
- Кандидат с исправлением: `1703ff46` (ветка `fix/factcheck-ambiguous-context`) — **НЕ задеплоен** на момент наблюдения.
- Режим доступа: read-only. Никаких записей в БД, рестартов, Telegram-трафика. SQLite открывалась как `file:...?mode=ro` + `PRAGMA query_only=1`.

---

## 1. Как кейс был найден

### 1.1 Локальные данные (шаг 1, без прод-доступа)

| Источник | Что найдено |
|---|---|
| `local_database.db` (рабочая копия, 12 KB) | только `smart_cache`, сообщений нет |
| `pre_migration_20261007_010900.db` | 60 000 сообщений, окно 2026-10-05…10-06 — окно не пересекается с кейсом |
| `local_database_2026-09-04_history.db` (755 MB), `backups/local_database_20260920.db` | старее кейса |
| `WorkspaceData/backups/adminbot-postmigration-2026-10-29/local_database.db` (1.67 GB, 2 050 649 сообщений) | данные по **2026-10-29 06:48 UTC** — кейса ещё нет |
| `OPENCODE_WORKFLOW_SCRATCH/**`, `plans/features/**/evidence` | трасс/дампов с этим кейсом нет |

Проверенные локальные запросы (окно 2026-08-01…2026-10-29):

- `select … from smart_messages where lower(text) like '%фейк%' order by timestamp desc limit 60`
- `… where lower(text) like '%майнкрафт%' …`
- `… where lower(text) like '%возможно%' and lower(text) like '%фейк%'` → единственный кандидат `tg:1117973` (2026-09-28 18:20:02, «в тгк было, возможно и фейк»).
  Этот кандидат **отклонён**: ни одного сообщения с `reply_to_id = 1117973` нет, `mca_factcheck_runs` по нему отсутствует — к описанной цепочке он не относится.
- `… where lower(trim(text)) = 'фактчек'` по всем чатам — триггеры есть, но в локальном бэкапе кейс не воспроизводится.

Вывод шага 1: локальные копии обрываются на 2026-10-29, кейс — позже. Переход к шагу 2.

### 1.2 Production (шаг 2, соблюдение fail2ban-дисциплины)

- 1 recon-коннект (короткий, `BatchMode`, `ConnectTimeout=15`): хост `vps159032-gqg`, `/var/www/admin_bot/local_database.db` (1.71 GB), `sqlite3` CLI отсутствует → Python 3.12.3 read-only.
- Далее 4 основных прогона тем же ключом, последовательно, без ретраев и параллельных коннектов. Один из прогонов повторён из-за порчи кодировки в локальном выводе (PowerShell); данные с сервера во всех прогонах идентичны.
- Все запросы — `SELECT`. Ни одного `INSERT/UPDATE/DELETE`, ни одного рестарта, ни одного Telegram-запроса.

Ключевые выборки:

```sql
-- триггеры фактчека с 2026-10-28
select chat_id, tg_message_id, reply_to_id, datetime(timestamp,'unixepoch'), author_name, text
from smart_messages where timestamp >= 1793200000 and lower(text) like '%фактчек%';

-- прогоны фактчека
select run_id, trigger_tg_message_id, target_tg_message_id, datetime(created_at,'unixepoch'),
       factual_verdict, reason, stage_trace
from mca_factcheck_runs where created_at >= 1793200000;

-- машинная трасса стадий (единственный сохраняемый след гейта)
select id, datetime(ts,'unixepoch'), event_name, stage, outcome, reason_code, entity_ids
from mca_events where ts between 1793983500 and 1793983720 order by ts;
```

Дискриминирующий факт: с 2026-10-29 в чате было **12** сообщений-триггеров «фактчек»
(`1184677, 1186270, 1186794, 8233, 8287, 1191050, 1191144, 1194078, 1194108, 1197782, 1201664, 1201759`).
Для **11** из них существует строка `mca_factcheck_runs` (обычный вердикт-путь).
Ровно для одного — **`tg:1201664`** — строки прогона нет, а в `mca_events` есть событие с
`pipeline_path = "v2_gate:ambiguous"`. Это и есть кейс.

### 1.3 Часовой пояс (важно для воспроизведения)

Системные часы прод-хоста идут на **+4 часа** относительно фактического UTC:
`datetime('now')` = `2026-11-06 20:50:11`, при этом сообщение, полученное «сейчас», имеет epoch → `2026-11-06 16:50`.
`smart_messages.timestamp` — epoch из Telegram (истинный UTC).
Поэтому в журнале `journalctl` окно кейса — `20:44–20:48` (локальные часы), в БД — `16:44–16:48` (UTC).
Кейс произошёл примерно за 4 минуты до первого прод-чтения.

---

## 2. Восстановленная цепочка

Чат: **`-1002661910336`** (основной супергруп, второй подключённый чат — `-1004482340693`, в кейсе не участвует).
Время — UTC. Формат ID: `tg:<message_id>` (Telegram message_id в этом чате).

### 2.1 Исходная тема (Minecraft-строительство)

| ID | Время | Автор | Содержание (фрагмент) |
|---|---|---|---|
| `tg:1201549` | 16:04:36 | Вася | фото + «зацените хуйню построил» |
| `tg:1201550` | 16:06:51 | Даня | «Хуйня 👍» |
| `tg:1201552` | 16:07:14 | Даня | «Так ты хуйню и строил» |
| `tg:1201553` | 16:07:55 | Папаха | фото (ответ на `1201549`) |
| `tg:1201554` | 16:08:21 | Вася | голосовое: «15 на 15 на 15, и там чистое.» |
| `tg:1201650` | 16:27:43 | Папаха | «построил говоришь» (ответ на `1201549`) |
| `tg:1201651` | 16:28:22 | Папаха | **видео** (постройки) |
| `tg:1201652` | 16:28:53 | Папаха | «бля сшакалилось» |

### 2.2 Родительская YouTube-публикация (Shorts)

| ID | Время | Автор | Содержание |
|---|---|---|---|
| `tg:1201653` | 16:28:54 | Папаха | `https://youtube.com/shorts/Jl-KVNhnMjo?si=…` |
| `tg:1201661` | 16:44:31 | Вася | «а не вордедит ли ты часом» (ответ на видео `1201651`) |
| `tg:1201662` | 16:45:25 | Папаха | «да тоже подумал хули он ебался если в вордедите можно ctrl+c Ctrl+v делать» |

Публикация подтверждена независимо через YouTube oEmbed (публичный HTTP, без прод-доступа):
`video_id = Jl-KVNhnMjo`, `author_name = lowkiMC`, `title = "This feels like a scene from interstellar 🥹"`.
`lowkiMC` — Minecraft-билдер; «вордедит» = WorldEdit, т.е. спор о том, что постройка скопирована, а не построена.

### 2.3 Триггер и цель

| Роль | ID | Время | Автор | Текст |
|---|---|---|---|---|
| **target** | `tg:1201663` | 16:45:38 | Папаха | «возможно... ФЕЙК» |
| **trigger** | `tg:1201664` | 16:45:46 | Вася | «фактчек» (`reply_to_id = 1201663`) |

`tg:1201663` — не reply, но стоит внутри непрерывной ветки `1201651 → 1201661 → 1201662 → 1201663`
(разрыв 16:28:22…16:45:38, всё в одном окне контекста). `tg:1201665` в `smart_messages` отсутствует (удалено/не доставлено).

### 2.4 Ответ бота

| ID | Время | Событие |
|---|---|---|
| — | 16:45:46 | `factcheck_target` (target resolve) |
| — | 16:45:49 | `factcheck_admission`, `pipeline_path = v2_gate:ambiguous` |
| — | 16:45:49 | `factcheck_temporal` `deliver/skipped` |
| — | 16:45:49 | `factcheck_cooldown` `refund:ambiguous` |
| `tg:1201666` | 16:46:05 | Вася: «окак» — единственная наблюдаемая реакция на ответ бота |

Текст отправленного сообщения в БД **не сохраняется** (см. §5), поэтому точная формулировка не восстановима.
Наблюдаемое поведение (жалоба владельца + событие гейта + код) согласуется: короткий уточняющий вопрос
вместо проверки тезиса, при том что тема (постройка/WorldEdit/Shorts) была в том же окне.

---

## 3. Что происходило в FactCheck-прогоне

### 3.1 Машинная трасса (дословно из `mca_events`)

`factcheck_target`, 16:45:46, `component = factcheck.target`, `outcome = success`:

```json
{"target_source": "explicit_reply", "target_kind": "unresolved",
 "target_tg_message_id": 1201663, "claim_origin": "target_text",
 "claim_anchor_tg_message_id": 1201663, "claim_anchor_source": "literal",
 "text_claim_resolved": false,
 "media_expected": true, "media_dependency_source": "adjacent_media_candidate",
 "association_attempted": true, "association_status": "ambiguous",
 "association_reason": "adjacent_before", "association_candidates": 2,
 "linked_media_ids": [], "media_notice_emitted": true,
 "media_notice_reason": "ambiguous_no_text_claim",
 "route": "orchestrator_v2", "trigger_tg_message_id": 1201664,
 "delivery_reply_to": 1201663, "contextual_target": false}
```

`factcheck_admission`, 16:45:49, `stage = v2_gate:ambiguous`:

```json
{"target_resolved": true, "explicit_request": true, "claim_items_count": 0,
 "admission_decision": "ambiguous_target", "reason_code": "multiple_dispute_candidates",
 "pipeline_path": "v2_gate:ambiguous", "verdict_stage": "",
 "cooldown_outcome": "refund:ambiguous"}
```

`reason_code = multiple_dispute_candidates` — это ровно `_REASON_AMBIGUOUS`
(`services/factcheck_suitability.py:87`), т.е. гейт вернул `DECISION_AMBIGUOUS`.

### 3.2 Состояние фич-флагов

| Факт | Значение | Чем доказано |
|---|---|---|
| v2-оркестратор фактчека включён | **ON** | `route = orchestrator_v2`, `pipeline_version = tf3`, `pipeline_type = temporal.factcheck` (при OFF шёл бы legacy-путь `handlers/factcheck.py` без этих событий) |
| Широкий контекст реально собирался | **да** | гейт вернул `multiple_dispute_candidates` (для этого нужен `ctx` с ≥ `_MIN_CONTEXT_MESSAGES = 5`, `services/factcheck_suitability.py:269`) |
| Кеш вердиктов | miss (прогона нет) | нет строки `mca_factcheck_runs`, `cache_hit` не применим |
| Точные значения `flags.factcheck_wide_context`, `limits.factcheck_context_before/after/messages` | **не читались** | это PostgreSQL, отдельный прод-коннект не делался; размер окна резолвится `resolve_window()` → `get_chat_param` (`services/factcheck_context.py:121–129, 528–529`) |

### 3.3 Решение suitability

`decision.decision = ambiguous_needs_clarification` (`DECISION_AMBIGUOUS`),
`reason_code = multiple_dispute_candidates`, `claim_items = ()` (`claim_items_count = 0`) —
типичный ambiguous: конкретный тезис не выбран, кандидатов несколько.
Дополнительно `text_claim_resolved = false`: целевой текст «возможно... ФЕЙК» сам по себе не является проверяемым утверждением.

### 3.4 Что получил Analyst

**Ничего.** Строки `mca_factcheck_runs` для `trigger 1201664` нет, `stage_trace` отсутствует.
Ветка `DECISION_AMBIGUOUS` возвращает управление **до** построения плана, поиска и Stage-1 Analyst
(`services/factcheck_orchestrator.py:1055–1072` в ревизии `a563ee31`).

### 3.5 Что получил Verbalizer

**Ничего.** Stage-2 Verbalizer в этой ветке не вызывается. Единственный LLM-вызов — `persona_short_reply`
(`services/factcheck_orchestrator.py:327` в `a563ee31`) с `_SHORT_REPLY_INSTRUCTION`.
Фактический вход этого вызова (по коду ревизии `a563ee31`, строки 1055–1057):

```
situation = f"Сообщение участника: «{req.target_text}». В контексте чата несколько тем спора — уточни тезис."
```

т.е. в модель уходил **только текст цели** — «возможно... ФЕЙК» (два слова),
без `ctx` (ConversationContext), без `decision.claim_items`, без ссылки на Shorts и на WorldEdit.

### 3.6 Что было доставлено

Текст ответа не сохраняется ни в `mca_bot_outputs`, ни в `bot_replies`, ни в `smart_messages`
(все три выборки по окну 16:45:30–16:47:30 вернули `n = 0`).
Достоверно: ответ был отправлен (событие `deliver` + `send_chunked_reply` в коде + реакция «окак» через 19 с),
и к нему мог добавляться media-notice (`media_notice_emitted = true`, `media_notice_reason = ambiguous_no_text_claim`,
код `a563ee31:1060–1066`). Формулировку модели восстановить нельзя.

---

## 4. Точная стадия потери смысла

**Потеря происходит в ветке `DECISION_AMBIGUOUS` оркестратора: уже посчитанный `ConversationContext`
не передаётся в генерацию ответа.**

Ревизия в проде `a563ee31` (`services/factcheck_orchestrator.py`):

- `:827` — `decision, ctx = await fsg.evaluate_with_expansion(...)` — контекст **уже собран**;
- `:1055` — `if decision is not None and decision.decision == fsg.DECISION_AMBIGUOUS:`;
- `:1056–1057` — `situation` строится **только** из `req.target_text`; `ctx` и `decision.claim_items` не используются;
- `:1058–1066` — единственный `persona_short_reply`, затем `send_chunked_reply`;
- `:1071` — `return _finish(OUTCOME_AMBIGUOUS, "v2_gate:ambiguous")` — Analyst/Verbalizer не запускаются.

Тот же код в рабочем дереве репозитория (master): `services/factcheck_orchestrator.py:410` (сбор контекста) и `:426–428` (ветка).
Гейт: `services/factcheck_suitability.py:526–533` и `:547–550` (решение ambiguous), причина `:87`.

Итого стадийная цепочка:

1. **Reply восстановлен корректно** — `target_source = explicit_reply`, `target_tg_message_id = 1201663` (не потерян).
2. **Семантический контекст собран** — `ctx` с темой Minecraft/WorldEdit/Shorts существует, гейт по нему и вынес «несколько тем».
3. **Потеря** — при формировании `situation` для короткой реплики контекст отброшен (шаг 3, ветка ambiguous).
4. **Analyst/Verbalizer не участвуют** — вердикта и проверки тезиса не было вовсе, поэтому «что проверять» и прозвучало.

Первичная причина не в Telegram-reply и не в сборке контекста, а в **передаче уже имеющегося контекста в
единственный LLM-вызов ветки ambiguous**.

---

## 5. Что восстановить не удалось и почему

| Не восстановлено | Причина |
|---|---|
| Точный текст ответа бота | короткая реплика уходит через `send_chunked_reply` и **не пишется** в `mca_bot_outputs` / `bot_replies` / `smart_messages`; Telegram Bot API не опрашивался (запрет на трафик) |
| Точный срез `ConversationContext` (какие именно сообщения попали в окно) | контекст живёт в памяти на время прогона и не персистится; окно зависит от `limits.factcheck_context_*` из PostgreSQL, которые не читались |
| Точные значения фич-флагов (`flags.factcheck_wide_context` и др.) | PostgreSQL не опрашивался (сознательное ограничение read-only прохода по SQLite) |
| Расшифровка медиа-кандидатов (`association_candidates = 2`) | `mca_media_assets`/`mca_media_analyses` для этих сообщений не входили в выборку; содержимое видео/фото `1201651`, `1201653`, `1201660` не анализировалось |
| Строка `reason_code` у события `deliver` | в БД `reason_code = null`, хотя код передаёт `ambiguous_needs_clarification` (см. §6.1) |

---

## 6. Побочные находки (не блокируют исправление, но важны)

### 6.1 Whitelist `REASON_CODES` молча обнуляет маркер этой ветки

`services/mca_events.py:587–588`:

```python
if key == "reason_code":
    event[key] = str(value) if value in REASON_CODES else None
```

`ambiguous_needs_clarification` в `REASON_CODES` отсутствует → `factcheck_temporal.deliver` пишется
с `reason_code = null`, хотя `tf.stage_event(..., reason_code="ambiguous_needs_clarification")` вызывается
(`a563ee31:1070–1072`). Единственный маркер, по которому ветку можно было бы найти в трассе, теряется.
Диагностировать кейс удалось только по `entity_ids` соседнего `factcheck_admission`.
Severity: medium (наблюдаемость), продуктового влияния нет.

### 6.2 Часы хоста +4 ч к UTC

`journalctl` и `datetime('now')` дают время на 4 часа больше фактического UTC (проверено сверкой с epoch сообщений Telegram).
Любые корреляции «лог ↔ сообщение» без поправки будут смещены на 4 часа. Требует отдельного решения (NTP/TZ), не правится в этом кейсе.

### 6.3 Ответы короткой ветки не попадают в аудит-таблицы

Ни `mca_bot_outputs`, ни `bot_replies` не содержат отправленный текст для gate-ветки.
Из-за этого невозможна постфактум-проверка публикации (в т.ч. требование «чистая смысловая публикация»)
без Телеграма. Кандидат-фикс `1703ff46` добавляет `_strip_raw_context`, но исходный текст всё равно не персистится.

---

## 7. Привязка

- Прод-ревизия кейса: `2.58.161` @ `a563ee31` (ветка ambiguous в этой ревизии — до-фиксная, проверено чтением файла ревизии).
- Исправление: `1703ff46` (не задеплоено на 2026-11-06 16:45 UTC).
- Требования карты: RCI-01 (воспроизведение по реальным ID — выполнено), RCI-02 (стадия потери — зафиксирована выше).
- Привязку evidence к строкам карты выполняет PM/Orchestrator; здесь — только диагностика.
