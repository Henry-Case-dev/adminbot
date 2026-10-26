# P0 FACTCHECK — production recon (PERMsoc)

Дата прогона: **2026-10-25 05:47:01 UTC** (сервер, `local=+0000`).
Метод: **один** SSH-логин `BatchMode`, один скрипт, без ретраев; только чтение.
PostgreSQL: `SHOW transaction_read_only = on`; SQLite: `mode=ro`; без записи, рестарта, checkout, сообщений в Telegram.

## 1. Окружение production

| Параметр | Значение |
|---|---|
| Дерево | `/var/www/admin_bot` |
| SHA | `534ac7dda6713fb407e0789fdddfa563251cdab4` |
| Версия | `2.58.130` (`APP_VERSION`) |
| Git | `branch=HEAD`, `describe=pre-asap2-2.58.33-784-g534ac7dd`, `git diff` пуст, 13 untracked |
| Unit | `admin_bot` — `active/running`, `NRestarts=0`, старт `2026-10-24 21:03:19 UTC` |
| Health | `http://127.0.0.1:8000/healthz` → **200**; `http://127.0.0.1/healthz` → 308; внешний `https://198.46.175.136/healthz` → 000 (TLS/SNI, не показатель) |
| SQLite | `/var/www/admin_bot/local_database.db`, 1 623 949 312 байт |

## 2. Кейс найден

Чат: **`-1002661910336`** — основной PERMsoc (подтверждается README/ARCHITECTURE: супергруппа `-1002661910336`, бот `@PERMsoc_bot`).

Событие: **2026-10-25 05:24:35 UTC**. Ответ бота «и че тут проверять, пустоту?» — из пула 5.3 `FACTCHECK_EMPTY_CONTEXT_PHRASES` (`services/smartmodule_phrases.py:30`).

## 3. Цепочка идентификаторов

| Этап | ID / время (UTC) | Факт |
|---|---|---|
| Альбом | `media_group_id=14343246299290082`, 10 фото, `2026-10-25 05:23:10` | Пересланная публикация канала **«НУЛЕВЫЕ+ @epoha00»**, `origin_message_id=45653`, `origin_sent_at=2026-10-24 12:17:54` |
| Подпись | `tg=1175403` | Единственная подпись альбома, **2846 символов**, на первом элементе |
| Цель reply | `tg=1175411` (9-й элемент) | `media_type=photo`, `text=''` (пусто), `media_group_id` есть, `is_forward=1` |
| Вызов | `tg=1175414`, `2026-10-25 05:24:35` | Текст «Фактчек», автор `Вася` (`user_id=1313107079`), `reply_to_id=1175411` |
| Ответ бота | **ID не сохранён** | См. §5 |

Альбом целиком (все `smart_messages` строки одного `media_group_id`, порядок по timestamp/id):

| tg id | media_type | text len | примечание |
|---|---|---|---|
| 1175403 | photo | **2846** | подпись публикации |
| 1175404 | photo | 0 | |
| 1175405 | photo | 0 | |
| 1175406 | photo | 0 | |
| 1175407 | photo | 0 | |
| 1175408 | photo | 0 | |
| 1175409 | photo | 0 | |
| 1175410 | photo | 0 | |
| **1175411** | photo | **0** | цель reply |
| 1175412 | photo | 0 | |

`reply_to_id` у цели пустой. `caption_entities` в БД не хранятся (колонок нет). Связь «изображение ↔ текст публикации» в хранилище есть только через `media_group_id`; подпись лежит на первом элементе. Начало подписи: «В 2007 г. вышла детская телепередача на палестинском телеканале Al-Aqsa TV…» (полный текст — 2846 символов в `smart_messages.text`).

Явно по цели `1175411`: **text — нет, caption — нет, photo — да, `media_group_id` — да, forward — да** (канал «НУЛЕВЫЕ+»). В БД сохранены `media_type=photo`, `media_group_id`, `is_forward=1`, `forward_source`, `origin_type=channel`, `origin_message_id=45653`; `caption_entities` не сохраняются (колонок нет).

## 4. Точка потери

Лог (journalctl, unit `admin_bot`):

```
2026-10-25T05:23:10.923 ... services.media_group_buffer - INFO - Media group buffer: insert | group=14343246299290082 first_msg=1175403 caption_len=2846 entries=1
2026-10-25T05:24:35.028 ... handlers.factcheck - INFO - [factcheck] triggered | chat=-1002661910336 user=1313107079
```

Дельта: **84.1 с** при TTL буфера **60 с** (`services/media_group_buffer.py:24`). На чтении `get_media_group_caption()` проверяет `time.monotonic() - record.ts > TTL_SECONDS`, удаляет запись и возвращает `None` (`services/media_group_buffer.py:97-102`).

Код prod-кандидата `534ac7dd`:

- `handlers/factcheck.py:414-427` — `_extract_target_text`: сначала `target.text or target.caption`; если пусто — `get_media_group_caption(mgid)`; иначе `None`.
- `handlers/factcheck.py:490-494` — `target_text = _extract_target_text(...)`; `if not target_text:` → случайная фраза 5.3, reply на `target.message_id`, **выход без поиска/LLM/vision**.

То есть «пусто» было зафиксировано **до** обращения к БД, альбому и vision. Подпись в этот момент **уже была сохранена** в `smart_messages` (строка `id=2363791`, `tg=1175403`, `text` = 2846 символов) — обработчик её просто не читал.

Подтверждение ветки: после `[factcheck] triggered` в journal нет ни `verdict sent`, ни `LLM failed`, ни `empty answer`; в `mca_factcheck_runs` **нет строки** с `trigger_tg_message_id=1175414` / `target_tg_message_id=1175411` (последний run в чате — от 2026-10-21). Ранний `return` 5.3 произошёл до temporal/v2-пайплайна.

### 4a. Поэтапно

| Этап | Что пришло / что сделано | Итог |
|---|---|---|
| Update | 10 фото, `media_group_id=14343246299290082`, пересланная публикация канала; подпись 2846 символов только на 1-м фото | принят |
| Reply resolver | «Фактчек» reply на 9-е фото `1175411`; `_parse_trigger` нашёл target | `[factcheck] triggered` |
| Storage | `smart_messages`: 10 строк; подпись сохранена как `text` у `1175403`; у `1175411` `text` пуст; `media_group_id` сохранён | данные есть |
| Album reconstruction (БД) | по `media_group_id` находятся все 10 строк и подпись | возможно, но не использовано |
| In-memory album buffer | `insert` в `05:23:10.923`, TTL 60 с | на `05:24:35` запись истекла |
| Vision | 10 активов, 5 `ready` / 5 `failed`; у цели `1175411` — `ready`, desc 268 | не вызван |
| Handler branch | `_extract_target_text` → `None` → фраза 5.3 | «пусто» без поиска/LLM/vision |

## 5. ID ответа бота

В `mca_bot_outputs` и `bot_replies` фразы «и че тут проверять, пустоту?» **нет**. Ответы factcheck отправляются через `services/smartmodule_utils._reply` (`:308-321`), который не пишет durable-ledger; поэтому точный Telegram-id ответа бота в БД отсутствует.

Единственное совпадение поиска по `%проверять%` — посторонняя строка `mca_bot_outputs.output_id=710`, `tg=1169618`, `sent_at=2026-10-22 01:09:17 UTC`, `source_feature=summary` (саммари, не factcheck).

Следствие: ID ответа бота не выдумываем. Ветка 5.3 доказана логами + отсутствием run-записи; фраза владельца совпадает с пулом 5.3.

### 5a. Последние factcheck-запуски в этом чате (для сравнения)

Все они текстовые и доходят до пайплайна; строки за 25.10 среди них нет.

| trigger tg | target tg | created (UTC) | verdict |
|---|---|---|---|
| 1169603 | 1169602 | 2026-10-21 22:21:19 | mixed |
| 1168989 | 1168987 | 2026-10-21 08:36:35 | insufficient_evidence |
| 1165726 | 1165725 | 2026-10-18 23:56:32 | supported / old_but_valid |
| 1165657 | 1165657 | 2026-10-18 21:06:00 | supported / old_but_valid |
| 1161268 | 1161264 | 2026-10-16 10:02:43 | insufficient_evidence |
| 1161110 | 1161108 | 2026-10-16 09:33:19 | insufficient_evidence |
| 1160607 | 1160602 | 2026-10-16 08:21:31 | insufficient_evidence |
| 1160300 | 1159921 | 2026-10-16 03:44:38 | insufficient_evidence |
| 1160229 | 1160229 | 2026-10-16 02:48:05 | insufficient_evidence |
| 1159919 | 1159900 | 2026-10-15 17:56:47 | insufficient_evidence |

## 6. Vision/OCR по альбому

Активы: **10/10** (`mca_media_assets`, `media_group_id=14343246299290082`). Анализы: revision 2, провайдер `dedicated`, модель `nvidia/nemotron-3.5-super-vl:free`.

| tg id | status | ocr_len | desc_len | error |
|---|---|---|---|---|
| 1175403 | failed | 0 | 0 | `parse_error` |
| 1175404 | failed | 0 | 0 | `parse_error` |
| 1175405 | ready | 0 | 166 | — |
| 1175406 | ready | 281 | 161 | — |
| 1175407 | failed | 0 | 0 | `vision_failed` |
| 1175408 | failed | 0 | 0 | `parse_error` |
| 1175409 | ready | 0 | 212 | — |
| 1175410 | ready | 0 | 156 | — |
| **1175411** (цель) | **ready** | **0** | **268** | — |
| 1175412 | failed | 0 | 0 | `parse_error` |

Итог: **5 ready / 5 failed**. У цели reply есть готовое визуальное описание (268 символов, OCR пуст). Даже без подписи вход не был пустым; но handler до vision не дошёл.

## 7. Конфигурация (PG, read-only)

| Ключ | Значение |
|---|---|
| `flags.factcheck_enabled` | `true` |
| `flags.factcheck_pipeline_v2` | `true` |
| `flags.factcheck_suitability_gate` | `false` |
| `flags.factcheck_wide_context` | `false` |
| `flags.vision_enabled` | `false` |
| `temporal.default_mode` | `contextual` |
| `temporal.tool_enabled` | `true` |

Per-chat overrides/keys для `-1002661910336` по factcheck/vision/temporal: **нет**.

Наблюдаемое противоречие: `flags.vision_enabled=false`, но intake и анализы 10 изображений реально выполнились (мастер `MCA_VISION_ENABLED` — env-only, default ON, `services/mca_gates.py:2148-2153`). Это отдельная находка для Builder/Architect; в рамках recon конфиг не менялся.

## 8. Выводы

1. **Корневая причина «пустоты»**: единственная подпись пересланного альбома хранится в in-memory буфере `MediaGroupCaptionBuffer` с TTL 60 с; в БД подпись есть, но `_extract_target_text` её не читает. Reply на 9-й элемент без собственной подписи через 84 с после альбома → буфер уже истёк → `None` → 5.3.
2. **Vision не участвовал**: у цели было готовое описание, но проверка «пусто» стоит раньше любых источников контента.
3. **Побочная находка**: 5 из 10 изображений альбома не разобраны (`parse_error`/`vision_failed`) — на сам кейс не влияет (цель `ready`), но ограничивает качество фактчека альбома.
4. **Побочная находка**: расхождение `flags.vision_enabled=false` и фактически выполненных vision-анализов.

## 9. Использованные read-only запросы (сокращённо)

```sql
-- SQLite, mode=ro
SELECT * FROM mca_bot_outputs WHERE content_text LIKE '%проверять%' OR content_text LIKE '%пустот%' LIMIT 8;
SELECT * FROM smart_messages WHERE text LIKE '%актчек%' ORDER BY timestamp DESC LIMIT 40;
SELECT * FROM smart_messages WHERE chat_id=? AND media_group_id=? ORDER BY timestamp, id;
SELECT * FROM mca_media_assets WHERE chat_id=? AND tg_message_id IN (...);
SELECT * FROM mca_media_analyses WHERE asset_id=? ORDER BY revision DESC LIMIT 5;
SELECT * FROM mca_factcheck_runs WHERE chat_id=? ORDER BY rowid DESC LIMIT 15;
SELECT * FROM mca_events WHERE chat_id=? AND ts BETWEEN ? AND ? ORDER BY ts LIMIT 150;
```

```sql
-- PostgreSQL, transaction_read_only=on
SHOW transaction_read_only;
SELECT "key", left(value::text,200) FROM bot_settings WHERE "key" IN (...);
SELECT x.k, left(x.v::text,200) FROM chat_profiles p, LATERAL jsonb_each(COALESCE(p.chat_params,'{}'::jsonb)) x(k,v) WHERE p.chat_id=$1;
```

## 10. Сырой вывод

`C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\fc-prod-recon\prod-recon-raw.txt`
(скрипт: `...\fc-prod-recon\prod-recon.sh`)

## 11. Безопасность

Один SSH-логин, publickey-only, `ConnectTimeout=20`, без повторов и параллельных коннектов. Запись в прод-БД/файлы/конфиг не выполнялась; Telegram-сообщения не отправлялись.
