# Задачи: youtube-multimodal-download-fallback-round1024

> **Раунд 10.24 (UPD4-B)** · Приоритет **P0** · Шаг 1 @PM · Тип: backend видео-пайплайн (YouTube URL-ветка)
> **ТЗ:** `plans/current_task.md`, секция **UPD4** (строка 277). Файл untracked; секреты не цитировать (R17/R18).
> **Baseline:** HEAD `00eab85`; прод `4314ea4`. Отчёт @Memory: `upd4-live-bug-clusters-round1024` (кластер B).
> **Конфликт/AMEND:** **граница архива** `plans/archive/video-multimodal-pipeline-and-incidents` (spec:37 «YouTube-URL-ветка mode=summary — байт-в-байт»; spec:241; FR-B5:52 «youtube+summary — текущий `summarize_cascade` L1/L2/L3 без изменений»). Осознанно **пересматривается**: скачать видео → мультимодалка → фолбэк субтитры.
> **UPD5 (строка 403):**
> - **№1 — подтверждено:** порядок уровней «**скачать видео → мультимодальная выжимка → фолбэк на субтитры**» окончательный. **Open Question №1 (порядок уровней) закрыт.**
> - **№2 — подтверждено:** **cookies / POT-provider (bgutil :4416) / resident-proxy на проде разрешены** → перенос из Open Questions **в scope** как **опциональный уровень для age-restricted** (значения только `.env`, R17/R18). **Open Question №2 (креды) закрыт.**
> - **№3:** команда «**транскрипт**» для YouTube отдаёт **голый транскрипт аудио курсивом** (отдельно от выжимки). Транскрибационный инструмент/канон — **F19 `media-transcribe-tool-round1024`** (ступень **F16 → F19**); F16 внутри себя сохраняет режим transcript, но финализацию разделения функций не ведёт.

## Цель
Запрос «Бот че за видос `<youtube-url>`» отвечает «автор зажал субтитры, пересказывать нечего». Причина: в OpenRouter уходит **URL страницы** (не файл) → мультимодалка физически не получает видеоряд → L1/L2 падают → L3 субтитры; для age-restricted субтитры **PERMANENT**. Нужно: **скачать видео → мультимодальная выжимка → при падении фолбэк на субтитры**, переиспользуя инфру нативной ветки (`download → media_share → summarize_media_url`).

## Что уже есть (координаты)
- URL-ветка summary: `handlers/youtube.py:1003-1069` (`_process_youtube_summary`: cache → `summarize_cascade` → фразы).
- Каскад в сервисе: `services/youtube_summarizer_service.py:46-48` (`_canonical_youtube_url` — **URL страницы**), `:62-154` (`summarize_cascade` L1/L2 → L3 субтитры).
- Субтитры/классификация: `services/youtube_transcript_engine.py:178-199` (yt-dlp `extract_info=None`), `:400-422` (transcript-api: `RequestBlocked/IpBlocked` → TRANSIENT, `AgeRestricted` → **PERMANENT**), `:148` (итоговое `YouTubeTranscriptUnavailableException`).
- Нативная инфра для переиспользования: `handlers/youtube.py:1130-1135` (kind=native), `:630-662` (`_publish_and_cascade`: `media_share.publish_media_file` → `_service.summarize_media_url`), `:957-968` (mode=summary: publish → L1/L2 → STT-фолбэк).
- `summarize_media_url`: `services/youtube_summarizer_service.py:235`.
- `media_share`: `services/media_share.py` (`publish_media_file`, `delete_file`, `enabled`); нативный fetch — `services/media_download.fetch_media_to_tmp`; downloader — `handlers/youtube.py:678-686` (`_download_url`).

## Задачи
- [x] **T-2313** [@Architect] spec/ADR: контракт «**скачать видео → мультимодалка → фолбэк субтитры**» для YouTube-URL; **AMEND/архивная граница** — зафиксировать, что прежний инвариант «YouTube-URL-ветка mode=summary байт-в-байт» пересматривается осознанно (только URL-ветка mode=summary; немедиа/иные триггеры не трогаются); флаг, откат, лимиты/бюджет времени. Учесть открытые вопросы владельцу (см. backlog).
- [ ] **T-2314** [@DevOps] Live-диагностика прода (read-only): подтвердить фактические причины L1/L2 (URL vs файл), `extract_info=None` на age-restricted, доступность POT-provider/proxy/cookies; снять конфигурацию (без значений секретов).
- [x] **T-2315** [@Builder] `handlers/youtube.py:1003-1069`: для URL+summary — **скачать видео** (существующий `_download_url`/`VideoDownloader`), **опубликовать** через `media_share` (`:630-662`) и вызвать `summarize_media_url`; при падении — **фолбэк на прежний субтитровый L3** (`summarize_cascade`/`summarize`). Учесть лимиты размера/длительности и `media_share.enabled()` (иначе честный фолбэк).
- [x] **T-2316** [@Builder] `services/youtube_summarizer_service.py:46-48,62-154`: не отправлять **URL страницы** в мультимодалку как видео — использовать опубликованный файл-URL; скорректировать `_canonical_youtube_url`/путь `summarize_cascade` так, чтобы L1/L2 получали видеоряд; сохранить `summarize_media_url`/`summarize_transcript` без регресса.
- [x] **T-2317** [@Builder] `services/youtube_transcript_engine.py`: корректная обработка `AgeRestricted` (PERMANENT) — понятная причина в лог/отчёт, без ложной «битой ссылки»; при наличии разрешённых владельцем cookies/POT/proxy — использовать (см. открытый вопрос №2). Не «глотать» причину.
- [x] **T-2318** [@Builder] **AMEND/архивная граница для YouTube-ветки:** обновить границы в spec/ссылках на `plans/archive/video-multimodal-pipeline-and-incidents` (spec:37/241, FR-B5:52) — зафиксировать расширение пайплайна; подтвердить, что cache-key, 🗿-молчание, 5.5/5.6/5.8-фразы и консьюм ведут себя как прежде. **Байт-в-байт сохраняется для всех немедиа/не-summary веток.**
- [x] **T-2319** [@Builder] Тесты: (a) скачивание→публикация→мультимодалка вызывается для youtube+summary; (b) падение мультимодалки → фолбэк на субтитры; (c) age-restricted → понятный фолбэк/причина, не «PERMANENT» без объяснения; (d) cache/🗿/фразы/кэш-инвалидация не сломаны; (e) `media_share` выключен → честный фолбэк.
- [ ] **T-2320** [@Reviewer] Ревью: пайплайн реально передаёт видеоряд, фолбэк работает, нет утечки подписанных URL (R17), границы не нарушены, тесты воспроизводят исходный баг (age-restricted кейс `1TON5W_SNKY`).
- [ ] **T-2321** [@DevOps] Деплой + live: «Бот че за видос `<youtube-url>`» → мультимодальная выжимка; age-restricted → понятный фолбэк; отчёт (секреты не цитировать).
- [x] **T-2337** [@Architect] **UPD5-корректировка:** зафиксировать в spec/ADR окончательный порядок уровней «**скачать → мультимодальная выжимка → фолбэк субтитры**» (Open Question №1 закрыт) и **вынести cookies/POT-proxy из Open Questions в scope** как **опциональный уровень для age-restricted** (Open Question №2 закрыт), значения только `.env` (R17/R18); уточнить `build_ytdlp_base_opts()`/порядок использования креды-уровня; граница с F19.
- [x] **T-2338** [@Builder] **Креды-уровень для age-restricted:** при age-restricted использовать разрешённую конфигурацию (cookies/POT-provider `:4416`/resident-proxy) — только из `.env`, значений в коде/логах нет; при недоступности/отсутствии — честный фолбэк с понятной причиной (без секретов в логе, R17).
- [x] **T-2339** [@Builder] **YouTube raw-транскрипт:** команда «транскрипт» для YouTube-URL отдаёт **голый транскрипт аудио курсивом** в том же стиле, что ГС/кружки (`format_transcript_html`/`_send_transcript_reply`), отдельно от выжимки; согласовать с F19 (T-2347) — ступень F16 → F19.
- [x] **T-2340** [@Builder] Тесты: (a) порядок уровней download→multimodal→subtitles воспроизводится; (b) age-restricted с разрешёнными кредами → транскрипт/выжимка; (c) без креды/при недоступности → честный фолбэк с причиной; (d) «транскрипт» YouTube → курсивный сырой транскрипт (не выжимка); (e) `AgeRestricted` больше не «PERMANENT» без объяснения; (f) cache/🗿/фразы не сломаны.
- [ ] **T-2341** [@Reviewer] Ревью: подтверждён порядок уровней; **креды не утекают** в git/логи/отчёт (R17/R18); различие выжимка/транскрипт; ступени F16→F19 соблюдены; границы архива.
- [ ] **T-2342** [@DevOps] Live: «че за видос `<youtube-url>`» → выжимка; «транскрипт `<youtube-url>`» → курсивный транскрипт; age-restricted с кредой/прокси → результат; без креды → понятный фолбэк; отчёт (секреты не цитировать).

## Критерии приёмки
- Для YouTube-URL+summary мультимодальная модель получает **видеофайл**, а не URL страницы.
- При падении мультимодалки работает фолбэк на субтитры; итог — выжимка либо честная понятная причина (не «пересказывать нечего» без объяснения).
- Age-restricted видео обрабатывается предсказуемо и объяснимо; при **разрешённых** cookies/POT/proxy — используется креды-уровень, иначе честный фолбэк (UPD5 №2).
- Команда «транскрипт» для YouTube даёт **голый транскрипт аудио курсивом**, не подменяясь выжимкой (UPD5 №3).
- Cache/🗿/фразы/консьюм не сломаны; полный pytest — 0 failed; `git diff --check` чист.

## Риски
- **R1 (High):** рост времени/стоимости ветки (до ~5–6 мин по NFR-4 архива) → таймауты/лимиты, флаг kill-switch; порядок уровней **подтверждён владельцем (UPD5 №1)**, оценка цены остаётся под наблюдением.
- **R2 (High):** скачивание YouTube требует POT/proxy/cookies → **владелец разрешил** (UPD5 №2) креды-уровень на проде; при недоступности/отсутствии — честный фолбэк с причиной; значения только `.env` (R17/R18).
- **R3 (High):** конфликт с архивным инвариантом «байт-в-байт» → явный AMEND T-2313/T-2318.
- **R4 (Medium):** подписанные `/media/` URL в логах → R17-маскирование (прецедент `_publish_and_cascade`).
- **R5 (Medium):** двойное скачивание/публикация, рост диска → TTL `media_share`, `finally`-уборка.

## Зависимости / ступени
- Зависит от: существующей инфры 10.23/архива `video-multimodal-pipeline-and-incidents` (media_share, summarize_media_url) — есть; `logging-infra-round1024` (причины в лог). **UPD5:** F19 `media-transcribe-tool-round1024` (разделение выжимка/транскрипт, канон 10, курсивный транскрипт) — ступень **F16 → F19**.
- Ступень общих файлов: `handlers/youtube.py` — **F16 → F19** (UPD5: финальное разделение функций транскрипт/выжимка ведёт F19); `services/youtube_summarizer_service.py` + `services/youtube_transcript_engine.py` — F16.
- Feature flag: `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED` (env-only `ClassVar`, **default ON**); при риске нагрузки — возможность OFF без деградации (фолбэк на прежний каскад). Поэтапная раскатка internal→10%→50%→100% — **на усмотрение владельца** (P0, высокая цена ошибки).
- Откат: флаг OFF → прежний субтитровый L3 / `git revert`; **Δ DDL = 0**, Δ каталога = 0 (если не потребуются параметры — решает @Architect).
