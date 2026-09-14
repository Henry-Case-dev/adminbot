# Фича F2 — `tool-download-quality-round1017` (Tool-calling скачивание + запрос качества)

> **Статус: ✅ COMPLETED** (14.09.2026; @Reviewer **APPROVED**, итерация 2). Реализовано T-1676…T-1683; гейты T-1675 (ADR-1017-2 опубликован) / T-1684 (@Reviewer/@PM) закрыты; архивировано (Step 8 @PM).
> **Spec:** [`spec.md`](spec.md) — ✅ создан @Architect (Step 2); **ADR:** [`adr-1017-2-tool-download-quality.md`](adr-1017-2-tool-download-quality.md) — ✅ создан, **SUPERSEDE ADR-1016-1** §2 п.3/§3.
> **Раунд:** 10.17. **Нумерация:** T-1675…T-1684 (продолжает T-1674).
> **Тип:** backend (LLM/tools/download). **Приоритет:** **P0** (прод-баг: tool-путь не скачивает и не спрашивает качество).
> **Зависимости:** — (гейт `flags.download_enabled`; переиспользует Fast-Track quality-меню). **Конфликт файлов:** `services/tool_router.py`, `tools/video_downloader.py`, `handlers/video_download.py`, `tools/video_download_phrases.py`, `services/media_send.py`, `services/tool_loop.py` (только при необходимости), тесты tool-calling.
> **Эпик:** `Epic: UPD3 багфиксы round1017` (@Memory, Step 0).
> **ТЗ:** `plans/current_task.md`, **UPD3** (строка 157): «Видео нормально скачивается старым способом (прямая команда "Бот, скачай") с выбором качества, а скачивание того же видео через tool calling не удалось и даже не спрашивает качество (должно спрашивать)…» + **UPD2** (строки 149–150, ошибка `DownloadError`).
> **Baseline:** HEAD `772f192`; pytest **5936 passed / 0 failed**; каталог **435/406/411/90/88/19** (Δ=0); SQLite **v9**; APP_VERSION 2.57.0.

## 0. Цель

Прямой путь Fast-Track (`Бот, скачай`) работает и **спрашивает качество**; tool-путь (`download_media` в LLM tool-loop) — **не скачивает и не спрашивает качество**.

**Конфликт ADR (требует SUPERSEDE):** **ADR-1016-1** (10.16, «Контракт скачивания») явно нормировал: «**Добавить `quality` в JSON-Schema `download_media` — Отклонён**: LLM не должен выбирать качество; Fast-Track-меню сохраняется», авто=`"max"`. **UPD3 требует обратного** (tool тоже должен спрашивать качество) → ADR-1016-1 в части JSON-Schema **отменяется** новым ADR-1017-2; остальные пункты ADR-1016-1 (контракт `download(url, quality?, progress_cb=None)`, ветвление direct/платформа по URL, reason-коды R17, bounded probe-fallback) сохраняются.

**Цель:** tool-путь скачивает так же, как Fast-Track, и инициирует запрос качества; устранён дефект падения; регресс-тесты; R17.

## 1. Доказательства (`file:line` на HEAD `772f192`)

- `services/tool_router.py:564-622` — `_download_media`: гейт `flags.download_enabled`, кулдаун, вызов `self.deps.downloader.download(url)` (без quality), фиктивный `tool_response` (`_download_status`, :109-…), отправка файла через media-send.
- `services/tool_router.py:21,239` — реестр tool `download_media`; JSON-Schema без поля `quality` (следствие ADR-1016-1 §3).
- `tools/video_downloader.py` — `download(url, quality=None, progress_cb=None)`, `_normalize_quality` (авто=`"max"`, legacy `"direct"`; мусор → `DownloadError(reason="invalid_quality")`); `_DOWNLOAD_QUALITIES`.
- `handlers/video_download.py:284-343` — Fast-Track: `probe(url)` → меню качества (инлайн-кнопки) → повторный `download(url, quality)` — **эталон поведения для tool-пути**.
- `tools/video_download_phrases.py` — пулы `VD_*_PHRASES` (в т.ч. `VD_ERROR_PHRASES`, «битая ссылка…»); пользовательская фраза при сбое.
- `services/media_send.py` — отправка файла в чат (фейковый `tool_response` F8/ADR-1015-3 §4).
- `services/tool_loop.py` — `TOOL_MAX_ROUNDS=4`, `_TOOL_CALLS_PER_ROUND_MAX=2` (не менять без ADR).
- **Предыдущий ADR:** `plans/archive/download-fix-round1016/adr-1016-1-download-contract.md` §2 п.3/§3 (quality в схему отклонён).

## 2. Требования (UPD3 §2, строка 157)

- [x] Tool `download_media` **скачивает** то же видео, что и Fast-Track (устранён дефект `DownloadError`/«битая ссылка» на tool-пути).
- [x] Tool-путь **спрашивает качество** как Fast-Track (`Бот, скачай`), а не молча берёт `max`.
- [x] Контракт запроса качества определён в ADR-1017-2 с **SUPERSEDE ADR-1016-1** (явное указание отменённого пункта).
- [x] `quality` (enum из `_DOWNLOAD_QUALITIES`) добавлен в JSON-Schema `download_media`; ответ пользователя разрешается в `download(url, quality)`.
- [x] Корнер-кейсы: нет ответа/таймаут; просроченный pending; вызов без ссылки; кулдаун; повторный даунлоад; лимиты tool-loop (4/2).
- [x] Успех — файл реально в чате; сбой — честный `status:"error"`; R17 (без URL/секретов в логах).
- [x] Регресс-тесты: direct `.mp4` и платформа (YouTube/TikTok, моки yt-dlp/cobalt).

## 3. Constraints (инварианты раунда)

- **R17:** в логи — только `tool`/`out_chars`/класс ошибки/`reason`; **без URL, текстов сообщений, cookies, ключей**; `{configured,last4}` для секретов.
- **R16:** id — ключ, не имя.
- **SQL/DDL не требуется** (pending-состояние — in-memory TTL, если ADR не решит иначе); каталог-инварианты **435/406/411/90/88/19** — **Δ=0** (quality-enum — код-константа `_DOWNLOAD_QUALITIES`).
- Гейт `flags.download_enabled` и download-кулдаун (D279 — touch только после успеха) — сохранить.
- Лимиты tool-loop (4 раунда / 2 вызова) — не менять без ADR.
- **Порядок роутеров `bot.py` не менять** (только DI-kwargs); `media/`/`.env` **не трогать**.
- **Ревью-гейты:** полный `pytest` 0 регрессий, R17-скан, `git diff --check`; русские conventional commits; атомарность (код + ADR/спека + тесты).

## 4. Зависимости / порядок

- **Вверх:** нет. **Вниз:** F5 (warnings-hygiene, независимо); релиз 10.17.
- **Порядок:** **первым** (прод-блокер); ADR-1017-2 (T-1675) — до реализации.

## 5. Definition of Done

- [x] Tool `download_media` для YouTube/TikTok (мок) и прямого `.mp4` — успех; файл в чате.
- [x] Tool спрашивает качество; выбранное качество применяется; pending-состояние истекёт по TTL.
- [x] ADR-1017-2 опубликован и содержит явный SUPERSEDE пункта ADR-1016-1 («quality в JSON-Schema отклонён»).
- [x] Регресс-тесты ask→answer→download, timeout, invalid quality, cooldown, direct/платформа.
- [x] Полный `pytest` **0 failed** (6007 passed); каталог **Δ=0** (`test_param_catalog` зелёный); R17-скан чист (`git diff --check` exit=0).

## 6. Чек-лист задач

- [ ] **T-1675 (@Architect, гейт):** ADR-1017-2 (**SUPERSEDE ADR-1016-1** §2 п.3/§3): контракт запроса качества в tool-loop, формат `quality` в JSON-Schema, хранение/TTL pending-скачивания (chat_id,url,qualities), поведение при исчерпании tool-rounds, R17-коды причин, корнер-кейсы. *(артефакт ADR создан; гейт закрывает @Reviewer/итерация)*
- [x] **T-1676 (@Builder):** добавить `quality` (enum `QUALITY_ENUM` ↔ `_ALLOWED_HEIGHTS`) в JSON-Schema `download_media`; обновить комментарии/реестр (ADR-1016-1 в части схемы помечен отменённым).
- [x] **T-1677 (@Builder):** tool инициирует запрос качества: возврат «ask»-статуса LLM (`needs_quality`) + сохранение pending (chat_id/user_id/url/qualities/ts, TTL 600с); callback `tdq:<height>` разрешается в `download(url, quality)`.
- [x] **T-1678 (@Builder):** устранить падение tool-пути (UPD3) — probe-first + явное int-качество, ветвление direct/платформа как Fast-Track (`handlers/video_download.py:284-343`), реальная отправка файла (`services/media_send.py`), честный `status:"error"`.
- [x] **T-1679 (@Builder):** единый источник качества Fast-Track ↔ tool (`QUALITY_ENUM`, `_normalize_quality`, `_ALLOWED_HEIGHTS`; тест паритета); без дублирования меню. **Ревью-итер.1 (M3):** построение клавиатуры/заголовка сведено в общий хелпер `services/media_send.send_quality_menu`/`build_quality_keyboard` — Fast-Track (`vd:`) и tool (`tdq:`) больше не держат независимых копий.
- [x] **T-1680 (@Builder):** TTL/очистка pending, взаимодействие с кулдауном (touch только после успеха — probe/download), отсутствие регресса лимитов tool-loop (4/2). **Ревью-итер.1 (L5):** tool-путь жжёт кулдаун после УСПЕШНОЙ отправки меню (провал доставки меню не оставляет пользователя без меню, но с кулдауном); L7 — `dispatch` catch-all логирует только класс исключения (R17).
- [x] **T-1681 (@Builder):** регресс-тесты `tests/test_tool_download_quality_round1017.py` (ask→answer→download direct/платформа, probe-fallback, stale/busy, cooldown, R17, schema/enum/ADR, tool-loop). **Ревью-итер.1:** +валидация высоты callback L1 (отказ до consume, pending сохранён), +проверка `send_chat_action` L6 (паритет UX).
- [x] **T-1682 (@Builder):** обновлена документация/ссылка ADR-1016-1 (banner SUPERSEDE, без переписывания истории) + spec/tasks; supersede зафиксирован.
- [x] **T-1683 (@Builder):** гейты: полный `pytest` **0 failed** (6007), каталог Δ=0, R17-скан, `git diff --check` (exit=0); коммит не делался (по указанию процесса).
- [ ] **T-1684 (@Reviewer + @PM, гейт):** сверка DoD, подтверждение SUPERSEDE ADR-1016-1, R17-tool-контракта и корнер-кейсов.

## 7. Открытые вопросы (@Architect → владелец)

- **Как именно** tool должен «спрашивать качество»: отдельный tool `ask_download_quality` + последующий `download_media(url, quality)`, или один tool со статусом `needs_quality` и повторным вызовом?
- Где хранить pending (chat_id→url/qualities) и какой TTL; нужен ли персист (PG) или in-memory достаточно?
- Что делать при молчании пользователя/просрочке pending: тихо скачать `max` или молчать?
- Учитывать ли выбор качества в `probe`-фоллбэке и в фразе-ошибке (новые пулы `VD_*_PHRASES`)?
- Разрешить ли LLM вызывать `download_media` без ссылки (по контексту «это видео») или только с явным URL?

## 8. Feature flag / progressive delivery

- **Feature flag:** новый не требуется — дефект-фикс поверх `flags.download_enabled`. При риске — kill-switch `flags.tool_download_quality_enabled` (решение @Architect); rollback = `git revert`.
- **Progressive delivery:** неприменим (исправление блокера); мониторинг — `[tools]`/`[videodl]`-логи (`error=`/`reason=`, без URL).
