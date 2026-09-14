# Фича F1 — `download-fix-round1016` (Багфикс скачивания: tool-путь + Fast-Track probe)

> **Статус: ✅ COMPLETED** (14.09.2026; @Reviewer APPROVED, итерация 2). T-1626…T-1632 + гейты T-1625/T-1633 закрыты; прод-смоук скачивания — @DevOps (Step 9).
> **Spec:** [`spec.md`](spec.md) · **ADR:** [`adr-1016-1-download-contract.md`](adr-1016-1-download-contract.md).
> **Раунд:** 10.16. **Нумерация:** T-1625…T-1633 (продолжает раунд 10.15 → T-1624).
> **Тип:** backend (tools/download). **Приоритет:** **P0 (High, прод-баг)**.
> **Зависимости:** нет (гейт — существующий `flags.download_enabled`).
> **Конфликт файлов:** `services/tool_router.py`, `tools/video_downloader.py`, `handlers/video_download.py`, `tools/video_download_phrases.py`; тесты `tests/test_tool_calling_round1015.py` (расширить/добавить новый).
> **Эпик:** `Epic: Багфиксы + полный аудит round1016` (@Memory, Step 0).
> **ТЗ:** `plans/current_task.md`, **UPD2** (строки 148-153, §1) + §1 строки 3-8.
> **Baseline:** HEAD `18a9aa1`; pytest **5774 passed / 0 failed**; каталог **435/90/406/411/88/19** (Δ=0); SQLite **v9**; APP_VERSION 2.57.0.

## 0. Цель

Устранить два независимых дефекта скачивания видео:
1. **Tool-путь (a):** `download_media` всегда вызывает `downloader.download(url, "direct")`; `direct` как quality невалиден → `ValueError` → `DownloadError("invalid quality: 'direct'")`. Работает только для прямых `.mp4`; YouTube/TikTok/платформы → гарантированный `DownloadError` (регресс F8 10.15).
2. **Fast-Track (b):** «Бот, скачай» → `probe(url)` падает `DownloadError` → пользователю `VD_ERROR_PHRASES` («битая ссылка…»). `probe` зависит от окружения: cookies (`YOUTUBE_COOKIES_FILE`), proxy (`YOUTUBE_TRANSCRIPT_PROXY_URL`), POT (`YTDLP_POT_PROVIDER`), cobalt (`COBALT_API_URL`); гипотезы: истёкшие cookies / бот-чек / мёртвый прокси / IP-бан.

Финальная цель — рабочий `download_media` в tool-loop и Fast-Track для платформенных ссылок, диагностируемые причины сбоя (R17), смоук-тесты с моками yt-dlp/cobalt.

## 1. Доказательства (`file:line` на HEAD `18a9aa1`)

- `services/tool_router.py:592-594` — `path = await asyncio.wait_for(self.deps.downloader.download(url, "direct"), timeout=_DOWNLOAD_TOOL_TIMEOUT)` — жёстко передаётся `"direct"` вместо выбора качества/авто.
- `tools/video_downloader.py:695-705` — `_normalize_quality(quality)`: `"max"` → ok; иначе `int(text.strip("pP"))` → `int("direct")` → `ValueError` → `DownloadError("invalid quality: 'direct'")`. Поход в сеть не происходит.
- `handlers/video_download.py:326-331` — `probe = await _downloader.probe(urls[0])`; `except DownloadError` → `logger.warning("[videodl] probe failed …")` → `await message.reply(random.choice(VD_ERROR_PHRASES))`.
- `tools/video_download_phrases.py:14` — пул `VD_ERROR_PHRASES` («битая ссылка или приватное видео…»).
- Тесты `tests/test_tool_calling_round1015.py` — используют **direct-URL `.mp4`** и `MagicMock` downloader → дефект не пойман.
- `services/tool_loop.py` — `TOOL_MAX_ROUNDS=4`, `_TOOL_CALLS_PER_ROUND_MAX=2` (не менять).

## 2. Требования (UPD2 §1)

- [x] Tool `download_media` корректно ветвит: прямой медиа-URL (`.mp4` и пр.) vs платформенный (YouTube/TikTok/…), без передачи `"direct"` как quality.
- [x] Fast-Track probe даёт **диагностируемый** лог причины сбоя (без URL/секретов, R17) и различает классы причин (cookies/proxy/POT/cobalt/платформа).
- [x] Смоук-тесты с моками yt-dlp/cobalt имитируют реальную работу (не только `.mp4` + MagicMock).
- [x] Поведение успеха — файл реально в чате; сбой → честный `status:"error"` (F8 10.15 сохранён).

## 3. Constraints (инварианты раунда)

- **Порядок роутеров `bot.py` не менять** (только DI-kwargs при необходимости).
- **R17:** в логи — только `tool`/`out_chars`/класс ошибки/диагностическая категория; **без URL, текстов, cookies, ключей**. `{configured,last4}` для секретов.
- **R16:** id — ключ, не имя.
- **SQL/DDL не требуется**; каталог-инварианты **435/90/406/411/88/19** — **Δ=0** (новые ключи не вводить; пути/таймауты — код-константы/существующие ключи).
- `media/`/`.env` **не трогать** (диагностика окружения — только чтение конфигурации).
- Совместимость с `flags.download_enabled` и кулдауном (D279 — touch только после успеха).
- **Ревью-гейты:** полный `pytest` 0 регрессий, R17-скан, `git diff --check`; русские conventional commits.

## 4. Зависимости / порядок

- **Вверх:** нет. **Вниз:** F3 `audit-recent-epics-round1016` (смоук download/probe), F5 (финализация).
- **Порядок:** первая фича раунда (прод-блокер).

## 5. Definition of Done

- [x] YouTube/TikTok (мок) — `download_media` успешен; прямой `.mp4` — без регресса.
- [x] `"direct"` больше не передаётся как quality; `_normalize_quality` не получает платформенный мусор.
- [x] Fast-Track probe: при сбое — категорийная причина в логе + пользовательская фраза; успех — файл в чате.
- [x] Смоук-тесты с моками yt-dlp/cobalt; существующий tool-calling тест расширен.
- [x] Полный `pytest` **0 failed** (5815 passed); каталог **Δ=0**; R17-скан чист.

## 6. Чек-лист задач

- [ ] **T-1625 (@Architect, гейт):** спека/ADR: контракт `download(url, quality?)` (прямой URL vs авто/качество), коды причин probe, схема R17-диагностики.
- [x] **T-1626 (@Builder):** `services/tool_router.py` `_download_media` — убрать передачу `"direct"`; ветвление direct-URL vs авто/выбор качества; сохранить таймаут/кулдаун/фиктивный `tool_response` F8.
- [x] **T-1627 (@Builder):** `tools/video_downloader.py` — валидный путь для авто/платформенных ссылок (не прогонять `int()` по невалидному токену; `"auto"`/`None`); без ломки существующих вызовов (`_DOWNLOAD_QUALITIES`).
- [x] **T-1628 (@Builder):** «Fast-Track probe-диагностика» (b) — категорийный лог причины (`cookies`/`proxy`/`pot`/`cobalt`/`platform`) без URL/секретов; проброс безопасного кода в пользовательскую фразу (опц. — общий пул сохранён).
- [x] **T-1629 (@Builder):** preflight-диагностика окружения скачивания (наличие/истечение cookies, прокси, POT-провайдер, `COBALT_API_URL`) — **чтение без секретов**, однократный безопасный лог при старте/сбое.
- [x] **T-1630 (@Builder):** смоук-тесты с моками yt-dlp/cobalt, имитирующие реальную работу (успех/бот-чек/истёкшие cookies/мёртвый прокси/unsupported status).
- [x] **T-1631 (@Builder):** регресс-тест direct `.mp4` vs YouTube/TikTok через `download_media` и Fast-Track `probe`; согласованность кодов ошибок.
- [x] **T-1632 (@Builder):** гейты: полный `pytest` **0 failed**, каталог Δ=0, R17-скан, `git diff --check`; русский commit.
- [ ] **T-1633 (@PM/@Reviewer, гейт):** сверка DoD, ревью корнер-кейсов и R17-диагностики, подтверждение F8-совместимости.

## 7. Открытые вопросы (@Architect → владелец)

- Ветвление direct vs авто: определять по расширению/`Content-Type` пробой или по домену? (риск лишнего сетевого запроса).
- Нужен ли отдельный безопасный «код причины» в пользовательской фразе или оставить общий пул `VD_ERROR_PHRASES`?
- Требуется ли ротация cookies/проверка прокси на прод-сервере (выходит за репо, потенциально @DevOps)?

## 8. Feature flag / progressive delivery

- **Новый flag не требуется:** дефект-фикс поверх существующего `flags.download_enabled`. Rollback = `git revert`.
- **Progressive delivery неприменим** (исправление блокера). Мониторинг — `[tools]`/`[videodl]`-логи.
