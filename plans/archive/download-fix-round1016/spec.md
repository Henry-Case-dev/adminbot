# Спека F1 — `download-fix-round1016` (Скачивание: tool-контракт + Fast-Track probe-диагностика)

> **Статус:** ✅ COMPLETED (14.09.2026; @Reviewer APPROVED, итерация 2). T-1625 закрыт.
> **Раунд:** 10.16. **Тип:** backend (tools/download). **Приоритет:** P0 (прод-блокер). **T-ID:** T-1625…T-1633.
> **ТЗ:** `plans/current_task.md` UPD2 (строки 148-153) + §1 (строки 3-8).
> **ADR:** [`adr-1016-1-download-contract.md`](adr-1016-1-download-contract.md).
> **Baseline:** HEAD `18a9aa1`; pytest 5774/0; каталог 435/90/406/411/88/19 (Δ=0); APP_VERSION 2.57.0.
> **Зависимости:** нет. **Вниз:** F3 (смоук download/probe), F5.

## 0. Цель

Устранить два независимых дефекта скачивания:
1. **(a) Tool-путь:** `_download_media` всегда передаёт `quality="direct"`; для YouTube/платформ `_normalize_quality("direct")` → `ValueError` → `DownloadError` **до похода в сеть**. Работает только прямой `.mp4`.
2. **(b) Fast-Track:** `Бот, скачай <ссылка>` → `probe(url)` (yt-dlp) падает → пользователю generic «битая ссылка». Probe гейтит и cobalt-платформы, диагностики окружения (cookies/proxy/POT/cobalt) нет.

Результат: tool `download_media` и Fast-Track работают для платформенных ссылок; причины сбоя классифицированы и логируются безопасно (R17); smoke-тесты с моками yt-dlp/cobalt.

## 1. Точки изменения (`file:line` на HEAD `18a9aa1`)

| Файл | Строки | Что |
|---|---|---|
| `services/tool_router.py` | 592-594 | `downloader.download(url, "direct")` — убрать `"direct"` |
| `services/tool_router.py` | 595-599 | лог `error=%s` (message может содержать URL) → R17-safe `reason` |
| `tools/video_downloader.py` | 126-142 | классы ошибок — добавить `reason` |
| `tools/video_downloader.py` | 283-301 | `download()` — контракт `quality: str \| None`; ветвление уже есть (`is_direct_media_url`) |
| `tools/video_downloader.py` | 386-399, 425-431 | `_format_selector`/`download_ytdlp` — требуют `int`/`max` |
| `tools/video_downloader.py` | 660-692 | `_request_tunnel` (cobalt) — требуют `max`/`int` |
| `tools/video_downloader.py` | 694-705 | `_normalize_quality` — принять `None`/`auto`/`best`/`direct`→`max` |
| `handlers/video_download.py` | 284-285 | direct-ветка: `download(url, "direct")` → `download(url, None)` |
| `handlers/video_download.py` | 302-307, 326-331 | классифицированный лог + phrase-роутинг + bounded fallback |
| `tools/video_download_phrases.py` | 11-15, 62-67 | переиспользование `VD_UNAVAILABLE_PHRASES`; новых пулов не вводим |
| `tests/test_tool_calling_round1015.py` | 214-268 | расширить: платформенный URL, `assert download(url, "auto"/None)` |

## 2. Контракт `download(url, quality)` (нормативно)

```
async def download(url, quality=None, progress_cb=None) -> Path
```

**Правила:**
1. **Ветвление direct vs платформа — только по URL, без сетевой пробы.** Используется существующий `is_direct_media_url(url)` (`_DIRECT_MEDIA_RE`: `.{mp4|webm|mov|mkv|avi|gif}` с учётом query/fragment). Content-Type/domain-проба **не вводится** (лишний сетевой запрос, риск таймаута). Решение зафиксировано в ADR-1016-1 §2.
2. **`quality` (канонические значения):**
   | Вход | Нормализация `_normalize_quality` | Семантика |
   |---|---|---|
   | `None`, `""`, `"auto"`, `"best"` | `"max"` | авто/наилучшее |
   | `"max"` | `"max"` | наилучшее (как есть) |
   | `"direct"` **(legacy)** | `"max"` | deprecated-алиас; для direct-URL не используется, для платформы = авто |
   | `"1080p"`, `"1080"`, `1080` | `"1080"` | конкретная высота (Fast-Track-кнопки) |
   | прочее (`"p"`, мусор) | — | `DownloadError(reason="invalid_quality")`, **без похода в сеть** |
3. **Direct-URL:** `download_direct(url, progress_cb)` — `quality` игнорируется (как сейчас).
4. **YouTube + `flags.ytdlp_for_youtube`:** `download_ytdlp(url, quality_norm, ...)` — `max`/int.
5. **Прочие платформы:** `_request_tunnel(url, quality_norm)` (cobalt) — `max`/int.
6. **Совместимость Fast-Track:** callback `vd:{quality[:-1]}` передаёт `"1080"` → `download_ytdlp` делает `int("1080")` — не ломается. `_DOWNLOAD_QUALITIES`/`probe.qualities` не меняются.
7. **Совместимость F8 10.15:** успех — только после реальной отправки; в LLM — фиктивный `tool_response`; `flags.download_enabled`, общий кулдаун 4e, `_DOWNLOAD_TOOL_TIMEOUT=180`, глобальный лок, очистка файла — не менять. Флаг `quality` в JSON-Schema `download_media` **не добавляется** (инструмент не запрашивает качество — значит авто).

## 3. R17 reason-коды и логирование

`DownloadError` (и подклассы) получают атрибут `reason: str` (safe-токен). Значения:
`invalid_quality`, `probe_timeout`, `probe_bot_check`, `probe_unavailable`, `probe_failed`, `busy`,
`direct_http_403`, `direct_http_4xx`, `direct_too_big`, `direct_failed`,
`ytdlp_bot_check`, `ytdlp_unavailable`, `ytdlp_drm`, `ytdlp_too_big`, `ytdlp_failed`,
`cobalt_down`, `cobalt_timeout`, `cobalt_error`, `cobalt_unsupported`, `tunnel_http`, `stream_failed`, `unknown`.

**Нормативные правила логов:**
- В `logger.*` попадает **только** `error=<ClassName> reason=<reason>` (+ уже существующие невредные поля: `tool`, `chat`, `chars`, `bytes`, `qualities`). **Сообщение исключения (`str(exc)`) с URL/путём — НЕ логировать** (закрывает существующее R17-нарушение в `handlers/video_download.py:303-304` и `:291-292`, где сейчас печатается `url`).
- Запрещено: URL, title, cookies, ключи, значения proxy.
- Диагностика окружения — только presence-булевы (см. §4.3).

## 4. Алгоритмы / псевдокод

### 4.1. `_download_media` (tool, `services/tool_router.py`)
```python
path = await asyncio.wait_for(
    self.deps.downloader.download(url),          # quality=None → авто
    timeout=_DOWNLOAD_TOOL_TIMEOUT)
except DownloadError as exc:
    logger.warning("[tools] download failed | tool=download_media | "
                   "error=%s reason=%s", type(exc).__name__, exc.reason)
    return _download_status("error", "Не удалось скачать видео")
except Exception as exc:                          # не DownloadError
    logger.warning("[tools] download failed | tool=download_media | error=%s",
                   type(exc).__name__)
    return _download_status("error", "Не удалось скачать видео")
```
Кулдаун: touch — как сейчас (после старта); при сбое `_download_media` не бросает (возвращает `status:"error"`).

### 4.2. `_normalize_quality` (`tools/video_downloader.py`)
```python
@staticmethod
def _normalize_quality(quality) -> str:
    if quality is None:
        return "max"
    text = str(quality).strip()
    if not text or text.lower() in ("auto", "best", "max", "direct"):
        return "max"                       # "direct" — legacy-алиас (deprecated)
    try:
        return str(int(text.strip("pP")))
    except ValueError:
        raise DownloadError(f"invalid quality: {text!r}",
                            reason="invalid_quality") from None
```

### 4.3. Env-preflight (`tools/video_downloader.py`)
```python
def download_env_summary() -> str:
    # только presence-флаги, БЕЗ значений/путей (R17)
    return (f"cookies={'set' if settings.YOUTUBE_COOKIES_FILE else 'absent'} "
            f"proxy={'set' if settings.YOUTUBE_TRANSCRIPT_PROXY_URL else 'absent'} "
            f"pot={'set' if settings.YTDLP_POT_PROVIDER else 'absent'} "
            f"cobalt={'set' if settings.COBALT_API_URL else 'absent'}")
```
- Вызов: однократно на процесс при **первом** сбое probe/download (`_ENV_LOGGED` module-флаг) — уровень `WARNING`, лог `[videodl] env | <summary>`.
- Плюс `probe` classification: timeout → `probe_timeout`; текст исключения содержит `_AVAILABILITY_SIGN_IN_MARKERS` → `probe_bot_check`; прочее → `probe_failed`. `DownloadUnavailableError` уже используется для unavailable.
- **Значения env не читаются в текст**; проверять только непустоту из `settings` (`.env` не трогать).

### 4.4. Fast-Track single-URL (`handlers/video_download.py:325-343`)
```python
try:
    probe = await _downloader.probe(urls[0])
except DownloadError as exc:
    logger.warning("[videodl] probe failed | chat=%s | reason=%s",
                   chat_id, exc.reason)
    _log_download_env_once()
    if not is_direct_media_url(urls[0]):          # cobalt-eligible → bounded fallback
        return await _download_without_menu(bot, message, urls[0], chat_id, user_id)
    phrase = _probe_error_phrase(exc.reason)      # unavailable/bot_check → VD_UNAVAILABLE_PHRASES
    await message.reply(random.choice(phrase))
    return None
```

`_download_without_menu`:
- Повторяет direct-ветку (progress `⏳ Скачивание без выбора качества…`), `download(url, None)`, `_send_file`.
- Кулдаун: `cooldown_touch` — **только после успешного старта** (как в direct-ветке, D279); probe-fail сам кулдаун **не жжёт** (важно: сначала перепроверить remaining, чтобы не обойти лимит).
- Провал → `_log_download_env_once()` + `_probe_error_phrase(exc.reason)` (не «битая ссылка», если причина `probe_bot_check`/`probe_unavailable`).
- Бюджет: одна попытка; глобальный лок/таймауты сервиса не меняются.

`_probe_error_phrase(reason)`:
- `{"probe_bot_check", "probe_unavailable"}` → `VD_UNAVAILABLE_PHRASES`
- `{"cobalt_down"}` → `VD_SERVICE_DOWN_PHRASES`
- `{"direct_too_big", "ytdlp_too_big"}` → `VD_TOO_BIG_PHRASES`
- иначе → `VD_ERROR_PHRASES` (общий пул сохранён).

### 4.5. Multi-URL путь (строки 345-359)
Не меняется: `_safe_probe` уже fail-soft. При всех `None` → generic `VD_ERROR_PHRASES`; при желании T-1627 может добавить reason-лог, но поведение сохраняется.

## 5. Конфиг / флаги

- **Новых параметров/флагов нет** (каталог-Δ=0). Гейт — существующий `flags.download_enabled`.
- Пороги/таймауты — существующие код-константы (`_PROBE_TIMEOUT_SECONDS`, `_YTDLP_DOWNLOAD_TIMEOUT_SECONDS`, `_COBALT_POST_TIMEOUT`, `_DOWNLOAD_TOOL_TIMEOUT`). Не менять.
- `quality="auto"`/`None` — код-контракт, не PG-ключ.
- Progressive delivery неприменим (багфикс блокера). Rollback = `git revert` + restart. Мониторинг: `[tools]`/`[videodl]` логи по `reason`.

## 6. Тест-план (T-1630/T-1631)

Файл `tests/test_tool_calling_round1015.py` (расширить) + новый `tests/test_download_round1016.py`.

| # | Сценарий | Ожидание |
|---|---|---|
| 1 | tool `download_media` + YouTube-URL, мок `downloader.download` | вызван `download(url)` / `download(url, "auto")`; `"direct"` НЕ передан |
| 2 | tool `download_media` + прямой `.mp4` | без регресса; отправка файла; фиктивный `tool_response` |
| 3 | `_normalize_quality`: `None`/`""`/`"auto"`/`"best"`/`"max"`/`"direct"` | → `"max"` |
| 4 | `_normalize_quality`: `"1080p"`/`"1080"`/`1080` | → `"1080"` |
| 5 | `_normalize_quality`: мусор (`"p"`, `"abc"`) | `DownloadError(reason="invalid_quality")`, сеть не тронута |
| 6 | `download()` с YouTube + `quality=None` (мок yt-dlp) | `download_ytdlp` получил `"max"`; файл возвращён |
| 7 | `download()` с TikTok/платформа (мок cobalt tunnel) | `_request_tunnel` получил `"max"`; файл возвращён |
| 8 | probe timeout | `reason="probe_timeout"`, лог без URL |
| 9 | probe bot-check (маркер sign-in) | `reason="probe_bot_check"`; Fast-Track → `VD_UNAVAILABLE_PHRASES` или fallback |
| 10 | Fast-Track probe-fail + cobalt-успех | fallback скачал и отправил файл без quality-меню |
| 11 | Fast-Track probe-fail + fallback-fail | классифицированная фраза; кулдаун не сожжён probe-fail |
| 12 | R17-скан: в логах нет `http://`/`https://`/URL/секретов | чисто |

Тесты **не требуют сети** (моки yt-dlp/cobalt/httpx). Gate-файл `tests/test_no_secrets_logging` (если есть) — расширить паттерны.

## 7. Риски и меры

| Риск | Мера |
|---|---|
| `"direct"` ещё где-то передаётся (вне двух точек) | `grep` перед мержем; `_normalize_quality` принимает алиас (защита от регресса) |
| Fallback без меню скачает не то качество | выбор максимального качества платформы (cobalt/yt-dlp), таймаут один; пользователь получает файл вместо ошибки |
| Fallback удваивает нагрузку при системном сбое cobalt | одна попытка, глобальный лок, probe-fail не жжёт кулдаун |
| Логи содержат URL (существующее нарушение) | заменить `%s`-URL на `reason` в изменяемых строках; R17-скан |
| Probe-fail на YouTube → fallback запустит тяжёлый yt-dlp | budget 1 попытка + `_YTDLP_DOWNLOAD_TIMEOUT`; результат важнее |
| Изменение `_normalize_quality` ломает cobalt enum | отдельные unit-тесты на `max`/int; Fast-Track кнопки шлют int |

## 8. Критерии приёмки (DoD)

- [ ] Tool `download_media` успешен на YouTube/TikTok (мок) и на прямом `.mp4`; `"direct"` как quality не передаётся.
- [ ] `_normalize_quality` не падает на `None/auto/best/direct`; возвращает `max`/int; мусор → `invalid_quality` без сети.
- [ ] Fast-Track: probe-fail даёт `reason`-лог (без URL), классифицированную фразу и bounded fallback для cobalt-платформ.
- [ ] Env-preflight: однократный presence-лог (`cookies/proxy/pot/cobalt` = set/absent), без значений.
- [ ] Smoke/unit-тесты (таблица §6) зелёные; полный `pytest` **0 failed**; каталог **Δ=0**; R17-скан чист; `git diff --check` чист.
- [ ] Инварианты: порядок роутеров `bot.py` не тронут; `media/`/`.env` не тронуты; F8-совместимость (фиктивный tool_response, кулдаун) сохранена.

## 9. Handoff

Реализация — @Builder: T-1626…T-1632; гейт — T-1633 (@PM/@Reviewer).
`@Orchestrator` — спецификация F1 готова.
