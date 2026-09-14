# Спека F2 — `tool-download-quality-round1017` (Tool-calling скачивание + запрос качества)

> **Статус:** ✅ COMPLETED (14.09.2026; @Reviewer **APPROVED**, итерация 2). Реализовано; ADR-1017-2 (SUPERSEDE ADR-1016-1 §2 п.3/§3) опубликован.
> **Раунд:** 10.17. **Тип:** backend (LLM/tools/download). **Приоритет:** P0 (прод-баг).
> **T-ID:** T-1675…T-1684. **ADR:** [`adr-1017-2-tool-download-quality.md`](adr-1017-2-tool-download-quality.md) — **SUPERSEDE ADR-1016-1** §2 п.3/§3 (quality в JSON-Schema).
> **Baseline:** HEAD `772f192`; pytest 5936/0; каталог 435/406/411/90/88/19 (Δ=0); SQLite v9.
> **ТЗ:** `plans/current_task.md` UPD3 (стр. 157) + UPD2 (стр. 149–150).

## 0. Цель

Fast-Track (`Бот, скачай`) скачивает и **спрашивает качество**; tool-путь (`download_media` в LLM tool-loop) — **падает** и **не спрашивает**. Требуется: tool скачивает как Fast-Track, инициирует запрос качества (кнопки в Telegram), устраняет дефект падения, покрыт регресс-тестами и R17.

**Корень дефекта (гипотеза, проверяемая):** tool-путь слепо вызывает `download(url)` → `quality`=`max` и **никогда не делает `probe()`**. Fast-Track сначала `probe(url)` (валидация доступности + список реальных качеств), затем скачивает с **явным int-качеством**; `max`-селектор yt-dlp/`videoQuality:"max"` cobalt на части роликов не собирается. Исправление — tool повторяет флоу Fast-Track.

## 1. Scope

**In scope:**
- Tool `download_media` инициирует запрос качества: `probe` → инлайн-клавиатура `tdq:<height>` → фиктивный `tool_response` `status:"needs_quality"`.
- Callback `tdq:` в роутере 4e доводит скачивание (download+send) — как `cb_pick_quality`.
- Прямые медиа-URL — скачивание сразу, без меню (как Fast-Track `:284-339`).
- Опциональный `quality` в JSON-Schema (enum): если пользователь **явно** назвал качество — скачать сразу без меню.
- Bounded fallback при провале `probe` (одна попытка `download(url, None)`), как Fast-Track `_download_without_menu`.
- Кулдаун: touch только после успеха (probe в ask-ветке / download в немгновенных); провал не жжёт (D279).
- Регресс-тесты; R17-логи (reason-коды, без URL).
- **SUPERSEDE ADR-1016-1** (ADR-1017-2).

**Out of scope:**
- Изменение лимитов tool-loop (`TOOL_MAX_ROUNDS=4`/`_TOOL_CALLS_PER_ROUND_MAX=2`).
- `TOOL_CALLING_TOOLS` порядок/состав (7 инструментов сохраняется).
- Переписывание `download(url, quality)`/reason-кодов ADR-1016-1 (кроме отменённого пункта про схему).
- Персистентное pending (PG/DDL нет — in-memory TTL).
- Fast-Track-флоу (`handlers/video_download.py:284-343`) — поведение сохраняется.

## 2. Точки изменения (`file:line` на `772f192`)

| Файл | Строки | Что |
|---|---|---|
| `services/tool_router.py` | 564-622 | переписать `_download_media`: probe→menu / direct / fallback; вынести `_download_now` |
| `services/tool_router.py` | 62-66 | +`_PROBE_TOOL_TIMEOUT`, `_TOOL_DL_PENDING_TTL_SECONDS` (код-константы, каталог-Δ=0) |
| `services/tool_router.py` | 109-113 | `_download_status` — статусы `success`/`error`/`needs_quality` |
| `services/tool_router.py` | (new) | TTL-pending store + `store_tool_download_pending`/`pop_tool_download_pending` |
| `services/tool_schemas.py` | 119-134 | `TOOL_DOWNLOAD_MEDIA`: +опциональный `quality` (enum), обновить `description` |
| `handlers/video_download.py` | 500-622 | +callback `F.data.startswith("tdq:")` → `cb_tool_quality` (download+send) |
| `handlers/video_download.py` | 190-208 | переиспользовать pending-паттерн/`_parse_int_suffix` |
| `tools/video_downloader.py` | 99-100 | публичная `QUALITY_ENUM` (единый источник enum для схемы) |
| `services/tool_loop.py` | — | **не менять** (лимиты) |
| `services/media_send.py` | — | **не менять** (переиспользуется) |
| `tests/test_tool_download_quality_round1017.py` | новый | регресс-тесты tool-пути |

## 3. Контракты

### 3.1. JSON-Schema `download_media` (после SUPERSEDE ADR-1016-1)
```json
{
  "name": "download_media",
  "parameters": {
    "type": "object",
    "properties": {
      "url": {"type": "string", "description": "Ссылка на видео."},
      "quality": {"type": "string",
                  "enum": ["max", "2160", "1440", "1080", "720", "480", "360"],
                  "description": "Заполняй ТОЛЬКО если пользователь явно назвал качество; иначе НЕ указывай — бэкенд сам предложит выбор кнопками."}
    },
    "required": ["url"],
    "additionalProperties": false
  }
}
```
`enum` берётся из `tools.video_downloader.QUALITY_ENUM` (единый источник с `_ALLOWED_HEIGHTS`); тест паритета обязателен.

### 3.2. `tool_response` (фиктивный, ADR-1015-3 §4)
| Ситуация | JSON |
|---|---|
| Файл отправлен | `{"status":"success","message":"Файл успешно загружен в чат"}` |
| Меню качества отправлено | `{"status":"needs_quality","message":"Пользователю предложен выбор качества — меню с кнопками отправлено в чат"}` |
| Сбой | `{"status":"error","message":"…"}` (без URL) |

### 3.3. Callback-контракт
- `tdq:<height>` — нажатие кнопки качества (`height` ∈ `{360,480,720,1080,1440,2160}`).
- Pending: key `(chat_id, user_id)`, поля `{url, title, qualities, trigger_message_id, expires}`; TTL `600 c`; ленивая чистка.
- Просрочка/нет pending → `callback.answer("эта менюха протухла")`.
- Busy (`downloader.busy`/`get_active`) → `callback.answer(VD_BUSY_PHRASES, show_alert=True)`.

## 4. Алгоритмы/псевдокод

### 4.1. `_download_media` (tools `services/tool_router.py`)
```python
async def _download_media(self, arguments, ctx) -> str:
    url = self._require_str(arguments, "url")
    if not _is_http_url(url):                       return _download_status("error", "Некорректная ссылка")
    if not hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED):
                                                    return _download_status("error", "Скачивание отключено")
    if ctx.bot is None or self.deps.downloader is None:
                                                    return _download_status("error", "Скачивание недоступно")
    cooldown = self._download_cooldown()
    if cooldown is not None and ctx.user_id is not None:
        cooldown_refresh(cooldown, hot.get("limits.download_cooldown", settings.DOWNLOAD_COOLDOWN))
        if await cooldown_remaining(cooldown, ctx.chat_id, ctx.user_id) > 0:
            return _download_status("error", "Скачивание на кулдауне — позже")

    explicit = self._quality_arg(arguments.get("quality"))   # None | "1080" (нормализует downloader._normalize_quality)
    # (а) явное качество ИЛИ прямой медиа-URL → без меню
    if explicit is not None or is_direct_media_url(url):
        return await self._download_now(ctx, url, explicit, cooldown)

    # (б) платформа → probe → меню качества
    try:
        probe = await asyncio.wait_for(self.deps.downloader.probe(url),
                                       timeout=_PROBE_TOOL_TIMEOUT)
    except DownloadError as exc:
        logger.warning("[tools] download probe failed | tool=download_media | "
                       "error=%s reason=%s", type(exc).__name__, exc.reason)
        return await self._download_now(ctx, url, None, cooldown)   # bounded fallback (без меню)
    except Exception as exc:
        logger.warning("[tools] download probe failed | tool=download_media | error=%s",
                       type(exc).__name__)
        return await self._download_now(ctx, url, None, cooldown)

    if cooldown is not None and ctx.user_id is not None:
        await cooldown_touch(cooldown, ctx.chat_id, ctx.user_id)    # D279: после успешного probe
    self._store_pending(ctx, url, probe.title, probe.qualities)
    await self._send_quality_menu(ctx, probe.title, probe.qualities)
    return _download_status("needs_quality",
                            "Пользователю предложен выбор качества — меню с кнопками отправлено в чат")

async def _download_now(self, ctx, url, quality, cooldown) -> str:
    path = None
    try:
        path = await asyncio.wait_for(self.deps.downloader.download(url, quality),
                                      timeout=_DOWNLOAD_TOOL_TIMEOUT)
    except DownloadError as exc:
        logger.warning("[tools] download failed | tool=download_media | error=%s reason=%s",
                       type(exc).__name__, exc.reason)
        return _download_status("error", "Не удалось скачать видео")
    except Exception as exc:
        logger.warning("[tools] download failed | tool=download_media | error=%s",
                       type(exc).__name__)
        return _download_status("error", "Не удалось скачать видео")
    if cooldown is not None and ctx.user_id is not None:
        await cooldown_touch(cooldown, ctx.chat_id, ctx.user_id)    # D279: после успешного download
    try:
        await send_media(ctx.bot, ctx.chat_id, path, reply_to=ctx.reply_to_message_id)
    except Exception as exc:
        logger.warning("[tools] media send failed | tool=download_media | error=%s",
                       type(exc).__name__)
        return _download_status("error", "Не удалось отправить файл")
    finally:
        try: path.unlink(missing_ok=True)
        except OSError: pass
    return _download_status("success", "Файл успешно загружен в чат")

def _quality_arg(self, raw):        # enum-значение из схемы → нормализованный "max"/"1080"; мусор → None (не роняем)
    if raw is None or str(raw).strip() == "": return None
    try:
        return self.deps.downloader._normalize_quality(raw)   # max/height; иначе DownloadError
    except DownloadError:
        return None
```

`_send_quality_menu(ctx, title, qualities)`: `ctx.bot.send_message(ctx.chat_id, f"{title[:200]}\n\nвыбери качество:", reply_markup=<кнопки tdq:height>, reply_to_message_id=ctx.reply_to_message_id, disable_web_page_preview=True)`. Кнопки — `i % _QUALITY_ROW_SIZE == 0` по 3 (как `_quality_keyboard` Fast-Track); `callback_data=f"tdq:{q[:-1]}"`.

### 4.2. Callback `tdq:` (`handlers/video_download.py`, роутер 4e)
```python
@video_download_router.callback_query(F.data.startswith("tdq:"))
async def cb_tool_quality(callback, bot=None):
    if _downloader is None or bot is None: return
    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    pending = pop_tool_download_pending(chat_id, user_id)    # из services.tool_router, TTL-чистка
    quality = _parse_int_suffix(callback.data, "tdq:")
    if pending is None or quality is None:
        await callback.answer("эта менюха протухла"); return
    if _downloader.busy or get_active(chat_id) is not None:
        await callback.answer(random.choice(VD_BUSY_PHRASES), show_alert=True); return
    await callback.answer()
    try: await callback.message.delete()                     # клавиатура уходит; как Fast-Track
    except TelegramBadRequest: pass
    reporter = ProgressReporter(bot, chat_id, trigger_message_id=pending["trigger_message_id"])
    register(chat_id, reporter); path = None
    try:
        await reporter.start("⏳ Скачивание…")
        path = await _downloader.download(pending["url"], f"{quality}p", progress_cb=reporter.on_progress)
        await reporter.finish("✅ Файл готов, отправляю…")
        await _send_file(bot, chat_id, path, pending["trigger_message_id"], pending["title"])
        await reporter.close()
    except Exception as exc:                                  # R17: класс/reason, без URL
        log_download_env_once()
        phrases = _fallback_phrases(exc)
        if not await reporter.fail(random.choice(phrases)):
            await _safe_error_reply(bot, chat_id, pending["trigger_message_id"], phrases)
    finally:
        if path is not None and path.exists(): path.unlink(missing_ok=True)
        unregister(chat_id)
```
**Кулдаун в callback: НЕ проверяется и НЕ жжётся** (producer уже проверил и сжёг после probe — как `cb_pick_quality`).

## 5. R17 / логирование

Нормативные логи (без URL/title/str(exc)):
```
[tools] download probe failed | tool=download_media | error=<Class> reason=<code>
[tools] download failed | tool=download_media | error=<Class> reason=<code>
[tools] download quality menu sent | chat=<id> | qualities=<n>
[tools] media send failed | tool=download_media | error=<Class>
[videodl] tool quality resolved | chat=<id> user=<id> quality=<h>p
```
Запрещено: URL, `str(exc)`, title, cookies, ключи. `_download_status` message — фиксированные фразы.

## 6. Тест-план (`tests/test_tool_download_quality_round1017.py`)

| # | Сценарий | Ожидание |
|---|---|---|
| 1 | tool + YouTube URL, мок `probe`/`download` | `needs_quality`; `send_message` с клавиатурой `tdq:`; `download` НЕ вызван |
| 2 | callback `tdq:1080` после (1) | `download(url, "1080p")`; `send_media` вызван; pending очищен |
| 3 | tool + прямой `.mp4` | `download(url, None)` сразу; клавиатуры нет; `success` |
| 4 | tool + `quality:"720"` (явно) | `download(url, "720")`; меню нет |
| 5 | tool, `probe`→`DownloadError(reason=probe_failed)` | одна попытка `download(url, None)`; меню нет |
| 6 | tool, probe-fail + download-fail | `error`; в логе `reason`; кулдаун не сожжён |
| 7 | callback, pending протух | `answer("эта менюха протухла")`; download не вызван |
| 8 | callback, `busy` | `answer(VD_BUSY_PHRASES, show_alert=True)` |
| 9 | tool, кулдаун >0 | `error "Скачивание на кулдауне"`; `cooldown_touch` НЕ вызван |
| 10 | R17: caplog после (1)-(6) | нет `http://`/`https://`/URL/секретов |
| 11 | schema: `download_media` params | `quality` enum == `QUALITY_ENUM`; `additionalProperties=false` |
| 12 | `TOOL_CALLING_TOOLS` | 7 инструментов, порядок/имена не изменены |
| 13 | tool-loop (мок LLM) | `download_media` → tool_response `needs_quality` → финальный текст; лимиты 4/2 не тронуты |
| 14 | ADR: файл `adr-1017-2` | содержит SUPERSEDE ADR-1016-1 §2 п.3/§3 |

## 7. Риски

| Риск | Мера |
|---|---|
| LLM всегда передаёт `quality` и обходит меню | description жёстко «только при явном запросе»; тест (4) + наблюдаемость лога |
| Pending-утечка в памяти | TTL 600 c + ленивая чистка (как Fast-Track `_get_pending`) |
| `_download_now` регресс для direct | тест (3); контракт `download` из ADR-1016-1 не меняется |
| Двойной touch кулдауна (producer+callback) | callback не трогает; тест (2)/(9) |
| Падение probe в tool-пути «маскирует» | bounded fallback + `reason` в логе (тест 5/6) |
| Дрейф enum схемы ↔ `_ALLOWED_HEIGHTS` | `QUALITY_ENUM` — единый источник, тест паритета |

## 8. Критерии приёмки (DoD)

- [x] Tool `download_media` для платформы спрашивает качество кнопками; выбранное качество применяется; файл в чате.
- [x] Прямой `.mp4` и явное `quality` скачиваются без меню.
- [x] Падение tool-пути устранено (probe-first + явное int-качество; bounded fallback).
- [x] ADR-1017-2 опубликован, содержит явный SUPERSEDE ADR-1016-1 §2 п.3/§3.
- [x] Pending истекает по TTL; лимиты tool-loop (4/2) не тронуты; кулдаун не жжётся при провале.
- [x] Полный pytest 0 failed (6007 passed); каталог Δ=0; R17-скан чист; `git diff --check` чист.

## 9. Feature flag / progressive delivery

- **Feature flag:** новый не требуется (дефект-фикс поверх `flags.download_enabled`). Kill-switch при риске — `flags.tool_download_quality_enabled` (решение отложено; вводить только при апруве владельца).
- **Progressive delivery:** неприменим (P0-фикс). Мониторинг: `[tools]`/`[videodl]` по `reason`/`quality` (без URL).

## 10. Handoff

`@Orchestrator` — спецификация F2 готова. ADR-1017-2 (T-1675) — до реализации; далее T-1676…T-1683 (@Builder), гейт T-1684 (@Reviewer/@PM).
