# Отчёт @Reviewer — раунд 10.23, ШАГ 5, фича F6 `summary-cover-rich-article-round1023`

- **HEAD ревью:** `7ade4d6` (F6), базовая ступень `1fea163` (F5).
- **Дата:** 19.09.2026.
- **Вердикт:** **Changes Requested** (1×High, 2×Medium, 4×Low).
- **Среда:** `.venv` → `aiogram 3.31.0`, `InputRichMessage.model_fields` содержит `media` → `_rich_media_supported() is True`.
- **Прогон:** полный `pytest -q` → **7289 passed / 0 failed** (94 c); целевой `tests/test_summary_cover_round1023.py` → **30 passed**; связанные (summary_two_call, summary_generator, outgoing_guard, param_catalog, prompt_migrations, verbilizer_response_modes) → **239 passed**. Заявленные цифры подтверждены.

---

## Findings

### [High] `services/telegram_send.py:195-199` — обложка в rich-канале собирается «сырым» HTML-тегом внутри `markdown`
`send_rich_message` для контента, распознанного как rich (`_looks_rich`), формирует:
```python
body = '<img src="tg://photo?id={}">\n\n{}'.format(cover_id, body)
rich = InputRichMessage(markdown=body, media=media_list)
```
Но официальный формат rich-markdown использует Markdown-синтаксис изображения `![alt](url)` (в т.ч. `tg://photo?id=…`), а не HTML-тег `<img>`; пример Telegram-фикстуры markdown содержит `![](https://telegram.org/example/photo.jpg)` и `![👍](tg://emoji?id=…)`, но НЕ содержит в markdown-режиме `<img src=…>`. HTML-путь `<img src="tg://photo?id=…">` документирован только для `html`-режима (и реализован в html-ветке `build_cover_article_html`).

**Почему это важно:** ветка `markdown` — это как раз основной путь для `deep_research` (единственный режим, где включается `FORMAT_RICH_BLOCK` и легальны таблицы). То есть в showcase-сценарии «лонгрид с обложкой» `<img>` почти наверняка не разрезолвится: либо обложка молча потеряется (пользователь увидит статью без обложки), либо Telegram отвергнет сообщение → тихий plain-фолбэк (пользователь вообще не получит Article). Симптом «тихий», поэтому баг не всплывёт в логах. Живой приёмки T-2156 ещё нет, тестами эта ветка не покрыта.

**Required fix:** в markdown-ветке использовать markdown-синтаксис ссылки на медиа (`![{caption}](tg://photo?id={cover_id})`, `caption` можно пустым) вместо HTML `<img>`; либо явно подтвердить возможность raw-HTML в markdown режиме (не подтверждается документацией) и закрепить тестом. Обязательно добавить тест, который для `_looks_rich`-контента + `media` проверяет фактически переданный `InputRichMessage` (что `markdown` содержит корректную ссылку на `tg://photo?id=summary_cover`, а не `<img>`), и/или закрыть это живой приёмкой T-2156 до статуса «готово».

### [Medium] `services/summary_generator.py:664-669` — даунгрейд rich→plain выполняется только для `deep_research`
```python
plain_text = (downgrade_rich_to_plain(text)
              if response_mode == "deep_research" else text)
```
Spec §3.4 (строка 103) и ADR-1023-6 п.11 требуют даунгрейда **при любом** переходе на plain-путь, независимо от режима. Условие по `response_mode` — это условие по «намерению», а не по фактическому содержимому. Если Narrator в `serious`/`casual` (или модель нарушит R11) отдаст Markdown/HTML, то `send_rich_message` выберет markdown-ветку, а при фолбэке на plain разметка не снимется → R11 нарушен (сырой Markdown уходит в `parse_mode=None`-сообщение).

**Почему это важно:** тихий фолбэк обязан не только не падать, но и не «протаскивать» rich-разметку в plain-канал; сейчас защита привязана к одному режиму, а не к контенту. Это хрупко и противоречит spec.

**Required fix:** определять необходимость даунгрейда по фактическому содержимому — переиспользовать `telegram_send._looks_rich(text)` (или сделать публичный детектор), т.е. `plain_text = downgrade_rich_to_plain(text) if _looks_rich(text) else text`. Добавить тест: `serious`-режим + rich-текст + ошибка `send_rich_message` → plain без `|`/`#`/тегов.

### [Medium] `tests/test_summary_cover_round1023.py` — не покрыты обязательные ветки фолбэка
- Нет теста «`TelegramRetryAfter` на **обеих** попытках → ровно 1 повтор, затем тихий plain» (spec §3.4/§7 п.6). Есть только успех повтора (`test_retry_after_one_retry_then_plain`), а ветка падения второй попытки не проверена.
- `test_guard_false_skips_cover` подменяет **всю** `_rich_media_supported` (monkeypatch), поэтому реальная логика определения `media` (`model_fields`/`__annotations__`) не исполняется. Spec §7 п.5 требует проверки «нет `media` → plain» на детекторе.
- `test_rich_media_supported_on_installed_aiogram` жёстко привязан к локальной версии aiogram (истина зависит от окружения) — тест хрупкий.
- Нет явной проверки `llm.generate.await_count == 2` на JSON-пути с непустым `cover_prompt` (инвариант `physical-two-call` на новом пути подтверждается только legacy-тестом) и нет проверки, что `cover_prompt` не инжектится в user-content Stage-2.

**Required fix:** добавить перечисленные тесты (двойной RetryAfter → plain; детектор `media` через фейковый тип/класс; `await_count == 2` для cover-JSON; отсутствие `cover_prompt` в Stage-2 messages). Убрать/изолировать env-зависимую проверку, чтобы тест не падал при aiogram < 3.31.

### [Low] `services/summary_generator.py:102-118` — `_rich_media_supported()` без кэша на процесс
Spec §3.4 говорит «кэшируется на процесс», реализация перепроверяет `model_fields` при каждом саммари (2 раза за прогон). Функционально безопасно, но это отклонение от контракта и лишняя работа на горячем пути. Рекомендация: `functools.lru_cache(maxsize=1)` или module-level кэш.

### [Low] Документационный дрейф контракта `generate_image`
Spec §3.3 и ADR п.3 описывают `generate_image(...) -> str | None` как «URL изображения в HTTPS-доступе». Фактическая F5-реализация (`services/image_generation.py:376-392`) возвращает **путь к локальному файлу**, и F6 корректно работает с ним как с путём (`tmp_path`, `os.remove`, `build_cover_media` читает байты). Код прав, но spec/ADR вводят в заблуждение относительно контракта. Рекомендация: поправить spec/ADR (F6-sync), чтобы контракт «локальный путь → байты в Telegram» был однозначен (это же закрывает R17-требование «keyed-URL не уходит»).

### [Low] `plans/docs/canon/architecture.md:200` — ступень `system2_handoff` не обновлена на `F3 → F6 → F7`
Spec §3.1 (строка 61) фиксирует `F3 → F6 → F7` («зафиксировать при Merge»), но канон-документ по-прежнему содержит `F3 → F7`. Канон-атомарность F6 (один коммит) формально требует синхронизации. Рекомендация: обновить строку в этом же фичевом контуре либо явным пунктом в Merge-чеклист.

### [Low] `services/summary_prompts.py:104-137` — двойной блок «ФОРМАТ ОТВЕТА (СТРОГО JSON…)» в Stage-1 промпте
После F6 в `SUMMARY_EDITOR_SYSTEM_PROMPT` два подряд JSON-формата: F3-блок (`{response_mode, digest}`) и F6-блок (`{response_mode, digest, cover_prompt}`). Формально второй — супермножество, но дублирование инструкций формата повышает риск рассинхрона/непонимания моделью. Рекомендация: оставить один итоговый форматный блок (F6-версию), а `cover_prompt`-описание — отдельным правилом.

### [Low] `services/param_catalog.py:393-396` — spec обещает widget `textarea`, в реестре `widget=""`
Ключ `prompts.summary_cover_style` создан с `widget=""` (как и остальные промпты). Рендер, вероятно, выводит textarea по конвенции категории `prompts`, поэтому функционально не ломается, но spec §3.2/§6 явно называет widget `textarea`. Рекомендация: либо выставить `widget="textarea"`, либо поправить spec под фактическую конвенцию.

---

## Контракт (чекбоксы)

1. **`cover_prompt` в том же JSON, `normalize_cover_prompt` never-raise, back-compat** — ✅ функционально. Stage-1 JSON расширен аддитивно (`system2_handoff.py:198-213`); не-строка/пусто → `""`; схлопывание `\s+`; обрезка по границе слова ≤300; legacy Markdown → `cover_prompt=""`. ⚠️ нет явного теста `await_count==2` на cover-JSON (см. Medium).
2. **Article через `sendRichMessage`, escape, guard, egress** — ⚠️ **ЧАСТИЧНО**. HTML-ветка корректна (`sanitize_outgoing` ДО `html.escape`, `<img src="tg://photo?id=summary_cover">`, exactly-one-of `html`); guard и egress-регистрация на месте. **Но markdown-ветка (основной `deep_research`-путь) использует HTML-тег `<img>` в markdown → обложка, скорее всего, не разрезолвится (High).**
3. **Тихий фолбэк (все ветки)** — ⚠️ **ЧАСТИЧНО**. `generate_image → None`, `TelegramBadRequest`/любое исключение → тихий plain без UX ✅; `TelegramRetryAfter` → 1 повтор ✅; дублей нет (rich не стримит) ✅. ❌ даунгрейд rich→plain только для `deep_research` (Medium); ❌ не покрыт двойной RetryAfter→plain.
4. **Канальный контракт UPD (Сценарий Б)** — ⚠️ **ЧАСТИЧНО**. `plain_no_tables` на rich не активен (`channel_enabled_rules`); rich-контент включается только для `deep_research` (`FORMAT_RICH_BLOCK`), что совпадает с UPD владельца («serious/casual — без Markdown»). Но фолбэк-даунгрейд не следует контракту «по содержимому» (Medium).
5. **Стиль обложки** — ✅. `prompts.summary_cover_style`, группа `prompts_summary`, `advanced` (resolve → advanced), `code_source=SUMMARY_COVER_STYLE_DEFAULT`, дефолт непустой `"photorealistic, cinematic light"`, конкатенация `compose_cover_image_prompt` с капом 300.
6. **Секрет/данные** — ✅. `build_cover_media` → `BufferedInputFile` (байты), keyed-URL в Telegram не уходит; промпт/URL не логируются (только класс ошибки / `reason`-код / числа); в коммите секретов нет; `httpx` INFO заглушен (F5).
7. **Δ каталога** — ✅ **не подгонка**. Фактически: REGISTRY **447**, categorized **422**, prompts-ключей **11**, Settings **416**, GROUPS **95**, `_TAB_BY_GROUP` **93**, TAB_RULES **20**; ключ реально существует, уровень advanced. Пин-тесты (10 файлов) обновлены корректно (446→447, 421→422), подмены нет.
8. **Инварианты** — ✅. `physical-two-call-pipeline` (cover_prompt — поле Stage-1, не третий вызов); egress-реестр (`send_rich_message` в `SEND_POINTS`, `handlers/info.py` в `SEND_ALLOWLIST`, `_SEND_RE` расширен); R16/R17/R18 соблюдены; `parse_mode=None` plain не тронут; F1–F5 не сломаны (полный pytest); `bot.py` не изменён (порядок роутеров цел).
9. **Тесты** — ⚠️ **ЧАСТИЧНО**: базовое покрытие хорошее, но отсутствуют ветки из Medium; тест guard-а тавтологичен (подмена всей функции).
10. **Полный pytest** — ✅ **7289 passed / 0 failed** (проверено лично).

---

## Список для @Builder (Changes Requested)

1. **`services/telegram_send.py:195-199`** — заменить в markdown-ветке `<img src="tg://photo?id=…">` на markdown-синтаксис `![caption](tg://photo?id=…)` (или документально подтвердить raw-HTML в markdown и закрепить тестом). Добавить тест на фактический `InputRichMessage` для rich+media (проверка, что markdown ссылается на `summary_cover`).
2. **`services/summary_generator.py:664-669`** — гейт даунгрейда сделать по содержимому (`_looks_rich(text)`), а не по `response_mode == "deep_research"`.
3. **`tests/test_summary_cover_round1023.py`** — добавить: (а) `TelegramRetryAfter` на обеих попытках → 1 повтор → тихий plain; (б) детектор отсутствия `media` (реальный `_rich_media_supported`, без подмены всей функции); (в) `await_count == 2` на cover-JSON; (г) отсутствие `cover_prompt` в Stage-2 messages; (д) даунгрейд rich→plain в `serious`/`casual`.
4. **`services/summary_generator.py:102-118`** — кэшировать `_rich_media_supported()` на процесс (spec §3.4).
5. **`services/summary_prompts.py:104-137`** — убрать дублирующийся JSON-форматный блок (оставить один итоговый).
6. **Canon/spec sync** — `plans/docs/canon/architecture.md:200` (`system2_handoff F3 → F6 → F7`); spec/ADR §3.3/п.3 — контракт `generate_image` = локальный путь (не URL).
7. **`services/param_catalog.py`** — привести widget к обещанному `textarea` либо поправить spec.

**Примечание:** живую приёмку `sendRichMessage` (T-2156) до устранения п.1 считать незакрытой — иначе рискуем «молча потерять» обложку на основном rich-сценарии.

`Верни исправленную версию. Текущий код отклонён.`

---

# Итерация 2 — повторный аудит (коммиты `1ffb066`, `92885cd`)

- **Вердикт итерации 2:** **Approved** (открытых Critical/High/Medium нет; 2×Low-наблюдения ниже — не блокируют).
- **Контекст:** поверх F6 влит F7 `8c46132` (correlation-id/usage-events) — его правки F6 НЕ приписываю. В частности, kwarg-и `module=…/step=…/correlation_id=…` в `llm.generate(...)` и `**kwargs` в тестовых фейках — F7.
- **Прогон:** полный `pytest -q` → **7331 passed / 0 failed** (96 c, лично, не флейк); целевой `tests/test_summary_cover_round1023.py` → **37 passed** (было 30); связанные (outgoing_guard/param_catalog/prompt_migrations/summary_two_call/verbilizer/summary_prompts) → **227 passed**.

## Закрытие findings итерации 1

| # | Sev | Статус | Доказательство |
|---|---|---|---|
| High-1 markdown-обложка | High | ✅ ЗАКРЫТО | `services/telegram_send.py:204-209`: `body = '![summary cover](tg://photo?id={})\n\n{}'`. Тест `tests/test_outgoing_guard_round1022.py::test_send_rich_message_markdown_cover_uses_markdown_link` проверяет **фактический** `InputRichMessage`: `rich.markdown.startswith("![summary cover](tg://photo?id=summary_cover)")`, `"<img" not in markdown`, таблица сохранена, `html/blocks is None`. Синтаксис `![alt](tg://photo?id=…)` соответствует официальному markdown-формату rich-сообщений. |
| Medium-2 даунгрейд по режиму | Medium | ✅ ЗАКРЫТО | `services/summary_generator.py:697`: `plain_text = downgrade_rich_to_plain(text) if looks_rich(text) else text`; режим из `_plain_fallback` убран, `_deliver_rich` больше не принимает `response_mode`. Тест `test_downgrade_by_content_in_serious_mode`: `serious` + таблица/`#` + `TelegramBadRequest` → plain без `|`/`#`, без UX. |
| Medium-3a двойной RetryAfter | Medium | ✅ ЗАКРЫТО | `test_retry_after_both_attempts_then_silent_plain`: `calls==2`, `rich==[]`, plain доставлен, `ux==[]`. |
| Medium-3b реальный guard `media` | Medium | ✅ ЗАКРЫТО | `test_detector_true_when_media_present` / `test_detector_false_when_media_absent` подменяют только `aiogram.Bot`/`aiogram.types.InputRichMessage` (фейк с/без `model_fields["media"]`), реальная логика `_rich_media_supported` исполняется. |
| Medium-3c `await_count==2` | Medium | ✅ ЗАКРЫТО | `test_cover_json_keeps_two_physical_calls` (`await_count == 2`). |
| Medium-3d изоляция Stage-2 | Medium | ✅ ЗАКРЫТО | `test_cover_prompt_isolated_from_stage2`: `SECRET_VISUAL_TOKEN`/`cover_prompt` отсутствуют в messages Stage-2. |
| Low-4 кэш guard | Low | ✅ ЗАКРЫТО | `@lru_cache(maxsize=1)` (`summary_generator.py:105`), тест `test_detector_cached_on_process`. |
| Low-5 spec/ADR sync | Low | ✅ ЗАКРЫТО | `spec.md:74/91/98`, `ADR-1023-6.md:33/34` — `generate_image` = локальный путь, markdown-ссылка/HTML-`<img>` зафиксированы. |
| Low-6 ступень `F3 → F6 → F7` | Low | ✅ ЗАКРЫТО | `plans/features/round1023-architecture.md:200/240` (уточнение: мой прошлый отчёт ошибочно ссылался на `plans/docs/canon/architecture.md` — таблица ступеней живёт в `round1023-architecture.md`). |
| Low-7 единый JSON-формат | Low | ✅ ЗАКРЫТО | `SUMMARY_EDITOR_SYSTEM_PROMPT.count("ФОРМАТ ОТВЕТА") == 1`; `_SUMMARY_EDITOR_F6_FORMAT` + `_MODE_RULES` + блок cover_prompt; тест `test_single_json_format_block`. |
| Low-8 widget `textarea` | Low | ✅ ЗАКРЫТО | `param_catalog.py:1821-1826` (`dataclasses.replace(..., widget="textarea")`), тест `test_summary_cover_style_widget_textarea`; факт: `widget == "textarea"`, level `advanced`. |

## Проверка после фиксов (итерация 2)

- **High-1:** ✅ обе ветки формируют корректный `InputRichMessage` (markdown → `![summary cover](tg://photo?id=summary_cover)`; html → `<img src="tg://photo?id=summary_cover">` + `media`). Тесты бьют по реальному payload, не тавтологичны. Обложка больше не теряется на `deep_research`.
- **Medium-2:** ✅ даунгрейд по содержимому работает для `serious`/`casual`; rich-разметка не протекает в `parse_mode=None`-plain.
- **Тесты фолбэков:** ✅ двойной RetryAfter, реальный guard `media`, `await_count==2`, изоляция `cover_prompt` — присутствуют и зелёные.
- **Инварианты:** ✅ `physical-two-call` (`cover_prompt` — поле Stage-1, `await_count==2`); тихий фолбэк без UX; egress-реестр не тронут (`send_rich_message` в `SEND_POINTS`, `handlers/info.py` в `SEND_ALLOWLIST`, `_SEND_RE` покрывает точку); R16/R17/R18 — промпт/URL не логируются, keyed-URL не уходит (байты/`BufferedInputFile`), секретов в коммитах нет.
- **Δ каталога:** ✅ REGISTRY **447**, categorized **422**, prompts **11**, Settings **416**, GROUPS **95**, `_TAB_BY_GROUP` **93**, TAB_RULES **20** — соответствует заявленному, не подгонка.
- **Канон-ступень:** ✅ `PREV_SUMMARY_EDITOR_R1023_F6` (текущий) байт-идентичен F3-канону (`7ade4d6^`), `PREV_*_F3` байт-идентичен F1-канону; `SUMMARY_EDITOR_RESPONSE_MODE_BLOCK` остался байт-в-байт прежним; `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS` согласованы.

## Остаточные наблюдения (Low, не блокируют Approved)

- **Low (migration-chain):** новый F6-канон отличается от промежуточного F6-канона коммита `7ade4d6` (там был дублирующий блок «ФОРМАТ ОТВЕТА»). Если бы PG успела замигрировать на промежуточный канон, `PROMPT_MIGRATIONS` не содержит его как `prev` → апдейт был бы `skip`. Для прода риска нет: коммит `7ade4d6` не деплоился (ветка ahead of origin, прод-база — `a8a6437`/10.22). Рекомендация на будущее: при правке уже «замёрженного» канона в том же контуре добавлять промежуточный слепок; для F6 достаточно зафиксировать в Merge-заметке.
- **Low (commit scope):** заголовок `1ffb066` — `fix(services,web,tests)`, но `web/` в коммите нет; косметика сообщения.

`**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.`
