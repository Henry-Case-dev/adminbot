# spec.md — F6 `summary-cover-rich-article-round1023`

> **Раунд 10.23** · Приоритет **P1** · Шаг 2 @Architect · Тип: backend/LLM + канон + egress + UI-настройка
> **ADR:** `ADR-1023-6.md` (**Accepted**, UPD владельца 19.09.2026 — Сценарий Б + обязательный aiogram). **Задачи:** `tasks.md` (T-2147…T-2156).
> **Синхрон с F3:** канальный контракт — `verbalizer-response-modes-round1023/spec.md` §3.6, ADR-1023-3 §Decision 10.
> **ТЗ:** `plans/current_task.md`, «Генерация изображений и Rich Text Саммари → 2. Расширение Саммари (Генерация обложек и Лонгриды)» (untracked; секреты не цитировать — R17/R18).
> **Сквозной слой:** `plans/features/round1023-architecture.md` §3.1, §3.4, §3.5, §6.
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**.
> **Зависит от:** F5 (провайдер/сервис изображений), F4 (канон-ступень), F3 (`response_mode`/JSON Stage-1), F1.

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| Двухвызовное саммари (Редактор → Рассказчик) | `services/summary_generator.py::_generate_two_call` (`:298-336`) |
| Оркестрация генерации и выбор канала отправки | `services/summary_generator.py::generate` (`:219-246`) |
| Стриминг / чанки | `services/summary_generator.py::_send_streaming` (`:453`), `_send_chunked` (`:516`), `_send_one_chunk` (`:532`) |
| Контракт handoff | `services/system2_handoff.py::validate_summary_digest` (`:128`), `parse_summary_handoff` (F3) |
| Промпт Редактора | `services/summary_prompts.py::SUMMARY_EDITOR_SYSTEM_PROMPT` (`:76`) |
| Каталог промптов Саммари | `services/param_catalog.py` группа `prompts_summary` (`:149`), `_PROMPTS` (`:369`) |
| Egress-реестр | `services/telegram_send.py:26` `SEND_POINTS`, `:35` `SEND_ALLOWLIST` |
| Рабочий rich-образец | `handlers/info.py:103-104,157-158` (`send_rich_message` + `InputRichMessage(html=…)`, fallback `TelegramBadRequest`, D231) |
| F5-сервис изображений (контракт-зависимость) | `services/image_generation.py::generate_image(...) -> str | None` (создаёт F5; ADR-1023-5) |

### 0.1. Ключевой конфликт и его решение

`generate()` сейчас **не различает** путь доставки: всегда `_send_streaming`/`_send_chunked` (plain). Article — принципиально другой канал (`sendRichMessage`, `parse_mode` не участвует). Решение: **отдельная ветка доставки Article**, которая включается только при (flag ON) ∧ (обложка получена) ∧ (aiogram поддерживает media). Во всех прочих случаях — **неизменённый** plain-путь (R11). Стриминг не трогаем.

---

## 1. Цель

Stage-1 «Редактор саммари» после текста выжимки отдаёт короткий **визуальный промпт на английском** (≤300 символов). Авторский **«Стиль обложки»** конкатенируется с визуальным промптом и уходит в image-API (F5). Финальное саммари доставляется нативным **Article** (`sendRichMessage`, Bot API 10.1+, обложка через `InputRichMessageMedia`) **с тихим откатом** на обычное текстовое саммари при любой ошибке.

## 2. Требуемое поведение

1. Stage-1 возвращает `cover_prompt` (EN, ≤300) в том же JSON, что `response_mode`/`digest`.
2. Валидатор нормализует/обрезает `cover_prompt`; отсутствие/мусор → `""` (Article не строится).
3. «Стиль обложки» (`prompts.summary_cover_style`) конкатенируется: `f"{style}. {cover_prompt}"` (trim/cap).
4. Article строится только при доступной поддержке rich-media; иначе — plain.
5. Любая ошибка генерации обложки/`sendRichMessage` → **тихий** plain-фолбэк (пользователю — ничего), лог только класс/код (R17).
6. Число физических LLM-вызовов **не растёт** (ровно 2; cover_prompt — поле того же JSON).
7. Plain-путь (стриминг/чанки, R11, `parse_mode=None`) байт-в-байт не сломан.
8. **Сценарий Б (UPD владельца):** Article — rich-канал, в нём **РАЗРЕШЕНО ВСЁ** — полный Markdown/HTML, сложные таблицы и сетки. Для `response_mode == deep_research` Stage-2 использует `FORMAT_RICH_BLOCK` (см. F3 §3.6).
9. **Апгрейд `aiogram >= 3.31.0` — ОБЯЗАТЕЛЬНОЕ условие F6/деплоя** (не опция): без него лонгриды с обложками не работают. `requirements.txt` уже пинит `>=3.31.0,<4.0.0`; локальный 3.29.1 → функциональность недоступна.

## 3. Архитектура и контракты

### 3.1. Stage-1 JSON и handoff (T-2149)

- Результат Stage-1 (`SET`): `{"response_mode": ..., "digest": "...", "cover_prompt": "<EN ≤300>"}`.
- F3 уже возвращает структурный результат `_generate_two_call` (добавляет `response_mode`); **F6 расширяет тот же объект полем `cover_prompt`** (additive). Если F3 выбрал иную форму — F6 расширяет её, не вводя второй контракт.
- Новый `normalize_cover_prompt(value) -> str` в `services/system2_handoff.py`:
  - не строка / пусто / `None` → `""`;
  - `strip`, замена всех пробельных пробегов (включая `\n`) на один пробел;
  - обрезка до **300** символов по границе слова (никогда не бросает);
  - не-ASCII не запрещаем кодом (EN — требование промпта, не жёсткий гейт).
- `parse_summary_handoff` читает `cover_prompt` → нормализует → кладёт в результат. Служебное поле **не** попадает в user-content Stage-2 и не логируется как содержимое (R17).
- **Ступень общего файла:** `services/system2_handoff.py` — `F3 → F6 → F7` (уточнение к §3.1 архитектурного документа; зафиксировать при Merge). F6 — строго после F3.

### 3.2. «Стиль обложки» (T-2150)

- Новый ключ каталога `prompts.summary_cover_style` (категория `prompts`, группа `prompts_summary`, `str`, widget `textarea`, **advanced**).
- **Δ каталога F6 = +1** (REGISTRY 439→440; categorized 414→415; settings-поля 409 не растут — PG-only промпт-ключ).
- Дефолт — код-константа `SUMMARY_COVER_STYLE_DEFAULT` (`services/summary_prompts.py`), в PG сидится `pg_db` по `code_source` (сид идемпотентен).
- Рантайм: `style = hot.get("prompts.summary_cover_style", SUMMARY_COVER_STYLE_DEFAULT)`.
- Конкатенация: `image_prompt = " ".join(x.strip() for x in (style, cover_prompt) if x.strip())[:300]` (финальный кап 300 — жёсткий).

### 3.3. Генерация обложки (F5-зависимость)

- F6 вызывает **только** `services/image_generation.py::generate_image(image_prompt, chat_id=...)` из F5.
- Контракт-зависимость (фактическая реализация F5, ADR-1023-5): возвращает `str | None` — **путь к локальному временному файлу** с байтами изображения (либо `None` при любой ошибке/дефиците бюджета); внутри — `response_format="url"` + серверное скачивание байтов, `worker_budget.consume`, fail-open. `None` → тихий plain-фолбэк.
- F6 **не** дублирует вызов провайдера, не хранит ключ, не знает деталей Pollinations; владеет временным файлом и удаляет его после отправки.
- В Telegram обложка уходит **байтами** (`BufferedInputFile`), не URL провайдера — keyed-URL не покидает сервер (R17).

### 3.4. Доставка Article (T-2151)

**Новая egress-точка.** В `services/telegram_send.py` добавляется обёртка:

```
async def send_rich_message(bot, chat_id, html, *, media=None, **kwargs)
```
- прогоняет **plain-источник** текста через `sanitize_outgoing` (инвариант 3) **до** сборки HTML;
- конструирует `InputRichMessage(html=html, media=media)` и вызывает `bot.send_rich_message(...)`.

**Регистрация egress:** в `SEND_POINTS` добавляется `"send_rich_message"` к `services/summary_generator.py`; `handlers/info.py` попадает в `SEND_ALLOWLIST` с обоснованием «текст справки — админ-канон/PG, не Stage-2 LLM». Тест покрытия `_SEND_RE` расширяется `|\.send_rich_message\(` (T-2154), чтобы новая точка не была «серой».

**Сборка Article (HTML-режим, подтверждён Bot API 10.2 / aiogram 3.30+):**
- `<InputRichMessage(html=..., media=[InputRichMessageMedia(id="summary_cover", media=InputMediaPhoto(media=<bytes>))])>`; `media` — `BufferedInputFile` из локального файла F5 (не URL); в HTML-режиме обложка ссылается как `<img src="tg://photo?id=summary_cover">`, в markdown-режиме — как `![summary cover](tg://photo?id=summary_cover)`; далее — абзацы текста саммари (`<p>`), разделённые пустой строкой.
- Текст саммари — plain (R11): `sanitize_outgoing` → `html.escape` → обёртка в `<p>` (порядок обязателен: sanitize ДО escape, иначе технические теги станут сущностями и не вырежутся).
- `id` медиа — константа `summary_cover` (```A-Za-z0-9_-```, 1–64).
- **Exactly-one-of:** заполняем **только** `html` (+`media`); `markdown`/`blocks` не используем.

**Guard совместимости aiogram (fail-safe):**
- `_rich_media_supported()` — проверка наличия поля `media` у `InputRichMessage` (dataclass `fields`) и атрибута `Bot.send_rich_message`; кэшируется на процесс.
- aiogram < 3.30 (локально 3.29.1) → `False` → Article-путь пропускается, plain. Это ровно требование ТЗ «тихий откат при несовместимой версии».

**Канальный контракт разметки — Сценарий Б (UPD владельца; синхрон с F3 §3.6 / ADR-1023-3 п.10):**
- Article = rich-канал: **полный Markdown/HTML и таблицы разрешены** (`InputRichMessage` — структурированный вход, text-`parse_mode` не применяется).
- При `response_mode == deep_research` digest может содержать таблицы/сетки — Article доставляет их без потери разметки (если digest rich — он передаётся как `markdown`/HTML; если digest остаётся R11-plain — текущий `<p>`-путь с escaping сохраняется).
- **Фолбэк обязан даунгрейднуть rich → plain:** при переходе на plain-путь (ошибка/несовместимость/дефицит бюджета) markdown/HTML и таблицы снимаются до отправки, иначе R11 нарушится, а таблицы дадут ParseError. Даунгрейд — детерминированный stripper, не regex-рез сущностей.
- `plain_no_tables` (F3) на rich-канале **не** активен.

**Путь доставки vs стриминг:**
- Ветка Article в `generate()`: если flag ON ∧ `cover_prompt` ≠ "" ∧ `_rich_media_supported()` ∧ URL получен → `send_rich_message(...)` **один раз** (без `_send_streaming`).
- Иначе → существующий plain-путь без изменений.
- Ретраи/`TelegramRetryAfter` для rich-пути: ровно 1 повтор по `retry_after`, затем тихий plain-фолбэк.

### 3.5. Тихий фолбэк (T-2152)

- Оборачиваем всю rich-ветку `try/except Exception` → **без** `_send_ux`, **без** сообщений пользователю; лог `logger.warning("summary cover: rich fallback | chat_id=%s | error=%s", chat_id, type(exc).__name__)` (только класс/код, R17).
- Фолбэк обязан отправить текст **один раз** (не дублировать, если rich частично ушёл): rich-ветка не стримит, поэтому дублей нет.
- Ошибка генерации изображения (`None`) — штатный путь фолбэка, не исключение.

## 4. Изменения по файлам

| Файл | Изменение |
|---|---|
| `services/summary_prompts.py` | инструкция `cover_prompt` (EN ≤300) в `SUMMARY_EDITOR_SYSTEM_PROMPT`; константа `SUMMARY_COVER_STYLE_DEFAULT`; слепок `PREV_R1023_SUMMARY_EDITOR_SYSTEM_PROMPT` |
| `services/system2_handoff.py` | `normalize_cover_prompt`; чтение `cover_prompt` в `parse_summary_handoff` |
| `services/summary_generator.py` | `_generate_two_call` отдаёт `cover_prompt`; rich-ветка в `generate()`; `_build_cover_article_html`; `_rich_media_supported` |
| `services/telegram_send.py` | обёртка `send_rich_message`; `SEND_POINTS["services/summary_generator.py"] += "send_rich_message"`; `SEND_ALLOWLIST["handlers/info.py"]` |
| `services/param_catalog.py` | ключ `prompts.summary_cover_style` (группа `prompts_summary`, advanced) |
| `services/prompt_migrations.py` | `PREV_R1023_SUMMARY_EDITOR_SYSTEM_PROMPT` → новый канон (ключ `prompts.summary_editor_system_prompt`, добавляет F8; отсутствие ключа → skip); `ROLLBACK_MIGRATIONS` |
| `config/settings.py` | `SUMMARY_COVER_ARTICLE_ENABLED` (env-only `ClassVar`, default ON, Δ каталога = 0) |
| `tests/` | новые тесты + осознанное обновление `test_param_catalog` (Δ +1) и `test_outgoing_guard_round1022` (расширение `_SEND_RE`) |

## 5. Канон-миграция (T-2153, ADR-1013-3)

- Атомарно одним коммитом (ступень канона `… → F4 → F6`): правка `SUMMARY_EDITOR_SYSTEM_PROMPT` + слепок `PREV_R1023_SUMMARY_EDITOR_SYSTEM_PROMPT` + запись в `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS` + `plans/docs/canon/**` + тесты.
- **Кросс-фичевый контракт:** PG-ключ `prompts.summary_editor_system_prompt` появляется только в F8. До этого шаг миграции `skip`-ается (механизм `migrate_prompt_canons` это допускает); после сида F8 значение == новому канону → no-op. Второго источника правды нет.
- `bot.py` вызывает `migrate_prompt_canons` без сдвига порядка существующих миграций.

## 6. Каталог: точная Δ

| Метрика | Было | Стало |
|---|---|---|
| REGISTRY | 439 | **440** |
| settings-поля | 409 | 409 |
| categorized | 414 | **415** |
| GROUPS | 92 | 92 |
| TABS | 20 | 20 |

Ключ: `prompts.summary_cover_style` — группа `prompts_summary`, категория `prompts`, widget `textarea`, уровень **advanced**. Пин-тесты обновляются в том же коммите.

## 7. План тестирования (T-2154/T-2155)

1. `normalize_cover_prompt`: пусто/None/не-строка → `""`; обрезка ≤300 по слову; схлопывание пробелов/`\n`; идемпотентность.
2. Конкатенация `style + cover_prompt` и финальный кап 300.
3. Разбор Stage-1 JSON с `cover_prompt`; отсутствие поля → `""` (graceful, F3-совместимость).
4. Article: сборка `InputRichMessage(html=…, media=[InputRichMessageMedia(id="summary_cover", …)])`; наличие `<img src="tg://photo?id=summary_cover">`; экранирование; exactly-one-of (`markdown`/`blocks` пустые).
5. Guard версии: при отсутствии `media` в `InputRichMessage` → plain-путь.
6. Тихий фолбэк: `generate_image → None`, `TelegramBadRequest`, любое исключение → plain, без `_send_ux`, без сообщений пользователю.
7. Egress: `send_rich_message` в `SEND_POINTS`; `_SEND_RE` ловит точку; `test_migrated_modules_have_no_bare_sends` зелёный.
8. Регресс plain: `_send_streaming`/`_send_chunked` без обложки не сломан (`test_summary_two_call_round1022`, `test_summary_generator`).
9. Канон: слепок/миграция/rollback.
10. Полный pytest — 0 failed.

## 8. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | aiogram < 3.31.0 → `media`/Article недоступны | **апгрейд `aiogram>=3.31.0` — ЖЁСТКОЕ условие деплоя** (requirements уже пинит); guard `_rich_media_supported` + тихий plain-фолбэк остаются только как defense-in-depth/локальный фолбэк, **не** как допустимый прод-режим |
| R2 | High | ломается стриминг/plain-доставка саммари | отдельная ветка Article, регресс plain-пути |
| R3 | Medium | egress-точка мимо guard | `send_rich_message` в реестре + расширенный `_SEND_RE` |
| R4 | Medium | обложка роняет саммари | `try/except` → тихий plain, без UX-сообщений |
| R5 | Medium | утечка покрытия/сырья в лог | лог только класс/код (R17) |
| R6 | Medium | канон-атомарность | один коммит + `ROLLBACK_MIGRATIONS` |
| R7 | Low | рассинхрон контракта с F5/F3/F8 | явные интерфейсы §3.3/§3.1/§5; Human Gate |

## 9. Критерии приёмки

- Редактор отдаёт `cover_prompt` (EN ≤300), валидируется; «Стиль обложки» конкатенируется и уходит в image-API (F5).
- Саммари приходит Article с обложкой; любая ошибка → **тихий** текстовый фолбэк с даунгрейдом rich→plain.
- **Сценарий Б:** в Article полный Markdown/HTML с таблицами разрешён; `plain_no_tables` на rich-канале не активен.
- **На деплое подтверждён `aiogram >= 3.31.0` (жёсткое условие).**
- Новая точка отправки в реестре egress; канон-миграция атомарна.
- Plain-путь/стриминг не сломан; полный pytest — 0 failed.

## 10. Feature flag / раскатка / откат

- `SUMMARY_COVER_ARTICLE_ENABLED` — env-only `ClassVar` вне каталога (**default ON**, Δ каталога = 0): OFF → обычное текстовое саммари, ни вызова обложки, ни Article.
- Раскатка internal→10%→50%→100% не требуется.
- Откат: kill-switch OFF → `git revert` + обратная канон-миграция (слепок `PREV_R1023_*`). Без DDL.

## 11. Зависимости / ступени

- **Зависит от F5** (сервис изображений + провайдер), **F3** (JSON Stage-1/`system2_handoff`), **F4** (канон-ступень), **F1** (канон-контур).
- Эксклюзивы: `services/summary_generator.py`, `services/summary_prompts.py`, `services/telegram_send.py`.
- Общие: `services/system2_handoff.py` (ступень F3 → **F6** → F7), `services/param_catalog.py` (ступень F2 → F5 → **F8** — F6 добавляет ключ в существующую группу `prompts_summary`, не меняя GROUPS).
- Канон-контур: `… → F4 → F6`.
- `handlers/info.py` — только чтение как образец.

## 12. Открытые вопросы (Human Gate)

1. ~~Подтвердить апгрейд aiogram до `>=3.31.0`~~ — **ПОДТВЕРЖДЕНО и ОБЯЗАТЕЛЬНО (UPD 19.09.2026):** без апгрейда лонгриды с обложками не работают. Жёсткое условие деплоя/живой приёмки.
2. Подтвердить формат обложки: `media` + `<img src="tg://photo?id=summary_cover">` (наш выбор) vs `blocks` + `InputRichBlockPhoto` (альтернатива). Выбран HTML-путь — ближе к рабочему образцу `handlers/info.py`.
3. Подтвердить дефолт `SUMMARY_COVER_STYLE_DEFAULT` (предложение: пустая строка — только визуальный промпт; либо «photorealistic, cinematic light»).
4. ~~Разметка в Article~~ — **РЕШЕНО владельцем (UPD 19.09.2026):** Сценарий Б разрешает полный Markdown/HTML с таблицами (см. §2 п.8 и §3.4).

## 13. Задачи

См. `tasks.md` (T-2147…T-2156). **T-2147** — этот spec + `ADR-1023-6.md` (выполнено).
