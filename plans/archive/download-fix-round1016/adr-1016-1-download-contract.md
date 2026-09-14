# ADR-1016-1 — Контракт скачивания: `download(url, quality?)`, авто-качество и probe-фоллбэк

> **Статус:** Accepted (Step 2 @Architect, 14.09.2026). **Раунд:** 10.16. **Фича:** F1 `download-fix-round1016`.
> **Связано:** ADR-1015-3 (tool calling), §8 `ARCHITECTURE.md`, прод-баг UPD2 (`2026-09-13T22:24:25`).

## 1. Контекст

`download(url, quality)` роутит: прямой media-URL → `download_direct` (quality игнорируется); YouTube → `download_ytdlp(url, quality)`; прочее → `_request_tunnel` (cobalt). Tool `download_media` (F8/10.15) и direct-ветка Fast-Track передавали `quality="direct"`, что валидно лишь для прямых файлов. Для любой платформы `_normalize_quality("direct")` → `ValueError` → `DownloadError` **до сети**. Плюс Fast-Track гейтится `probe()` (yt-dlp), из-за чего cobalt-платформы падают на «битой ссылке», хотя скачивание могло бы пройти.

## 2. Решение

1. **Контракт:** `download(url, quality: str | int | None = None, progress_cb=None) -> Path`.
2. **Ветвление direct vs платформа — по URL** (`is_direct_media_url`, regex-расширение с учётом `?`/`#`), **без** Content-Type/domain-пробы. Причина: детерминизм, отсутствие лишнего сетевого запроса и таймаута; расширение однозначно указывает на прямой стрим, платформенные ссылки расширения не имеют.
3. **Авто-качество = `"max"`.** `None`/`""`/`"auto"`/`"best"`/`"max"` и legacy `"direct"` нормализуются в `"max"`. `"direct"` сохранён как deprecated-алиас для защиты от остаточных вызовов; новые вызовы его не передают. Мусор → `DownloadError(reason="invalid_quality")` без сети.
4. **R17 reason-коды:** `DownloadError.reason` — safe-токен; логи содержат `error=<Class> reason=<code>`, никогда `str(exc)` (URL).
5. **Bounded probe-fallback (Fast-Track):** при сбое `probe()` для не-direct URL — одна попытка `download(url, None)` без quality-меню; при провале — классифицированная фраза. Probe-fail кулдаун не жжёт.

## 3. Рассмотренные альтернативы

| Вариант | Вердикт |
|---|---|
| Determined по домену/whitelist платформ | Отклонён: список платформ не закрыт, требует поддержки; extension-проба уже есть и надёжна для direct |
| Проба Content-Type HEAD перед выбором ветки | Отклонён: лишний сетевой запрос, таймаут, усложнение; ничего не даёт поверх extension-детекта |
| Добавить `quality` в JSON-Schema `download_media` | Отклонён: LLM не должен выбирать качество (UX-шум); Fast-Track-меню сохраняется |
| Убрать `probe()`-гейт полностью | Отклонён: quality-меню требует `probe.qualities`; fallback — точечная мера только для cobalt-eligible |
| Отдельный флаг на fallback | Отклонён: багфикс, не фича; rollback = `git revert` |
| Собственные reason-строки в user-фразах | Отклонён: переиспользуем существующие пулы `VD_*_PHRASES` (не расширяем UX-контракт) |

## 4. Последствия

- (+) Платформенное скачивание восстановлено и в tool-пути, и в Fast-Track; причины сбоя диагностируемы без утечки URL/секретов.
- (−) При системном сбое yt-dlp/probe возможна одна дополнительная попытка скачивания (ограничена глобальным локом и одним таймаутом).
- (−) `reason`-коды — новый внутренний контракт исключений; тесты обязаны проверять стабильность токенов.
- Инварианты: порядок роутеров `bot.py`, лимиты tool-loop (4/2), каталог-Δ=0, F8-совместимость — без изменений.
