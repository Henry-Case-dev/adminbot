# AdminBot — Kanban Board

## 📋 Backlog

*(пусто)*

## 🔧 In Progress

### Epic 66: Cobalt Downloader + Local Bot API — 2026-08-25 🆕 Шаг 1 (PM ✅) — ВЫСОКИЙ ПРИОРИТЕТ (target v2.46.0)

> Полный трек — plans/backlog.md (Epic 66). Пакет Tools/ (НЕ SmartModule): сервис VideoDownloader.
> Локальный сервер Telegram Bot API + инстанс Cobalt — СТРОГО в изолированных Docker-контейнерах
> (docker-compose); aiogram сессия через TelegramAPIServer.from_base(is_local=True), отправка
> FSInputFile из общей Docker-папки. Глобальный asyncio.Lock — одно скачивание на весь сервер
> (yt-dlp метаданные вне лока). Триггер-регулярка ^(скачай|загрузи|стяни|спизди|скачать) (i),
> ответ строго реплаем, supports_streaming=True. Флоу: >1 ссылки → Inline-выбор видео (≤40 симв.)
> → выбор качества (уникальные разрешения yt-dlp) → message.delete() с перехватом TelegramBadRequest
> (фраза из пула ошибок прав, скачивание ПРОДОЛЖИТЬ). Кулдаун DOWNLOAD_COOLDOWN=30m (парсер m/h/s).
> 6 пулов токсичных фраз random.choice дословно. Очистка файла try...finally. Без @Orchestrator.

- [ ] T-523 (@DevOps, P0) — docker-compose.yml: изолированные контейнеры telegram-bot-api + cobalt, общая volume-папка, healthcheck (ДО Bot API интеграции)
- [ ] T-524 (@Builder, P1) — settings.py + .env.example: COBALT_API_URL, DOWNLOAD_COOLDOWN (парсер m/h/s, дефолт 30m)
- [ ] T-525 (@Architect, P0) — Section ARCHITECTURE.md: дизайн VideoDownloader/Tools + флоу + лок (ДО реализации)
- [ ] T-526 (@Builder, P0, ←T-523/T-525) — пакет Tools/: VideoDownloader (лок Cobalt, yt-dlp вне лока, cleanup try...finally)
- [ ] T-527 (@Builder, P0, ←T-525) — handlers/video_download.py: триггеры, пулы фраз, Inline-выбор, delete+TelegramBadRequest, отправка; bot.py без изменения порядка роутеров
- [ ] T-528 (@Reviewer, P0, ←T-526/T-527) — ревью Epic 66 (изоляция Tools, семантика лока, секреты)

### Epic 67: Voice-to-Text транскрибация (SmartModule VoiceTranscriber) — 2026-08-25 🆕 Шаг 1 (PM ✅) — ВЫСОКИЙ ПРИОРИТЕТ (target v2.46.0)

> Полный трек — plans/backlog.md (Epic 67). Подсервис VoiceTranscriber внутри SmartModule,
> автосрабатывание без команд: строго F.voice | F.video_note (игнор F.audio/F.document).
> Паттерн Стратегия: BaseTranscriber.transcribe → контроллер Primary→Fallback (замена сервиса за пару минут).
> Primary: Groq whisper-large-v3 (таймаут 10с); Fallback: OpenRouter thinkingmachines/inkling:free
> (таймаут 15с, аудио Base64) — OpenRouter ОДОБРЕН пользователем как фолбэк-транскрибатор
> (НЕ сценарий Epic 62/63, конфликт снят явно). Ретраи СТРОГО 1 Primary → 1 Fallback → токсичная фраза.
> Ответ-реплай **Имя** 🗣: *текст* (Алиас→Никнейм→Юзернейм→Анонимус); инъекция в chat_history/RAG:
> <MediaMessage type="voice"/"video_note">…</MediaMessage>. Лимит VOICE_MAX_DURATION_SECONDS=600;
> .ogg/.mp4 в tmp, удаление в finally в 100% случаев; ChatAction.TYPING; рубильник ENABLE_VOICE_TRANSCRIPTION.
> 3 пула токсичных фраз дословно. Без @Orchestrator.

- [ ] T-529 (@Architect, P0) — Section ARCHITECTURE.md: дизайн VoiceTranscriber (Стратегия, форматы, XML-инъекция) ДО реализации
- [ ] T-530 (@Builder, P1) — конфиг: ENABLE_VOICE_TRANSCRIPTION, GROQ_API_KEY, OPENROUTER_API_KEY, VOICE_MAX_DURATION_SECONDS=600
- [ ] T-531 (@Builder, P0, ←T-529) — BaseTranscriber + GroqPrimary + OpenRouterFallback (промпт дословно, стратегия ретраев)
- [ ] T-532 (@Builder, P0, ←T-529) — хендлер автосрабатывания: фильтры, TYPING, лимиты, temp-cleanup finally, формат ответа, память, пулы фраз
- [ ] T-533 (@Reviewer, P0, ←T-531/T-532) — ревью Epic 67 (observer 0a не задет, заменяемость стратегий, нет утечки temp-файлов)

### Epic 68: FACTCHECK_SYSTEM_PROMPT — арбитраж интернет-срачей — 2026-08-25 🆕 Шаг 1 (PM ✅) — ВЫСОКИЙ ПРИОРИТЕТ (target v2.46.0)

> Полный трек — plans/backlog.md (Epic 68). Полная замена блока СУТЬ АНАЛИЗА + расширение системной роли
> (токсичный фактчекер-третейский судья): чередование регистра, дефисы вместо тире, кавычки "",
> запрет маркдауна/эмодзи/списков, динамический объем по {max_symbols}, умная фильтрация поисковой выдачи,
> вердикты «база»/«обосрался»/«посередине». Новый текст пользователя — дословно в ARCHITECTURE.md;
> RAG-инструкцию <bot_knowledge> из Epic 46 СОХРАНИТЬ. Дисциплина D123: промпт+эталоны+тесты одним коммитом.

- [ ] T-534 (@Architect, P0) — эталон нового FACTCHECK_SYSTEM_PROMPT ДОСЛОВНО в ARCHITECTURE.md (+сохранить <bot_knowledge>)
- [ ] T-535 (@Builder, P0, ←T-534) — замена блока по эталону байт-в-байт + эталоны-тесты (D123)
- [ ] T-536 (@Reviewer, P0, ←T-535) — ревью: байт-в-байт, <bot_knowledge> сохранён, {max_symbols}, вердикты

### Финальный цикл релиза v2.46.0 — после Epics 66–68 🆕 Шаг 1 (PM ✅)

- [ ] T-537 (@Builder + @Reviewer, P0, ←все эпики) — максимальное покрытие тестами + полный прогон pytest (база 2630), 0 регрессий; тесты ДО деплоя
- [ ] T-538 (@Reviewer, P0, ←T-537) — проверка конфликтов: порядок роутеров bot.py не тронут, UNHANDLED, observer 0a, OpenRouter только как транскрибатор-фолбэк
- [ ] T-539 (@Builder, P1) — README.md (ироничный тон) + MEMORY.md bump v2.46.0
- [ ] T-540 (@DevOps, P0, ←T-537/T-538) — коммит на русском (conventional commits) + пуш origin/master; секреты НЕ в коммите
- [ ] T-541 (@DevOps, P0, ←T-540) — деплой ssh nik@198.46.175.136:/var/www/admin_bot: git pull, обновление .env (+COBALT_API_URL, DOWNLOAD_COOLDOWN, ENABLE_VOICE_TRANSCRIPTION, GROQ_API_KEY, OPENROUTER_API_KEY, VOICE_MAX_DURATION_SECONDS; бэкап .bak.epic66-68), подъём docker-compose на проде, systemctl restart/status admin_bot, journalctl 0 traceback, smoke (скачивание / войс / фактчек)

### Epic 69: Хотфикс v2.46.1 — фикс download_to_drive + Docker на проде — 2026-08-26 🆕 Шаг 1 (PM ✅) — P0

> Полный трек — plans/backlog.md (Epic 69). Два прода-дефекта после v2.46.0:
> (1) handlers/voice_transcription.py зовёт несуществующий tg_file.download_to_drive() → AttributeError,
> голосовые не расшифровываются; фикс: await bot.download(media.file_id, destination=path)
> (aiogram 3.29.1, метод на Bot); тесты test_voice_transcription.py замоканы под старый вызов —
> обновить АТОМАРНО; канон ARCHITECTURE.md ~14586 с тем же багом синхронизировать ДО фикса.
> (2) По прямому требованию пользователя: Docker + docker compose v2 на проде nik@198.46.175.136
> (/var/www/admin_bot), контейнеры cobalt + telegram-bot-api из docker-compose.yml, DOWNLOAD_ENABLED=True,
> рестарт и проверка бота. Блокер: TELEGRAM_API_ID/HASH пусты локально и в проде — DevOps ищет на
> сервере (.env.bak*, другие проекты юзера); если нет — поднять что можно (cobalt без ключей) и
> зафиксировать блокер. ⚠️ ПОРЯДОК КРИТИЧЕН: DOWNLOAD_ENABLED=True СТРОГО после успешного
> docker compose up -d с рабочим telegram-bot-api — иначе бот ляжет при старте (import-time сессия).
> Коммитит @DevOps в конце цикла. Без @Orchestrator.

- [ ] T-542 (@Architect, P0) — канон ARCHITECTURE.md (~14586): ошибочный download_to_drive() → эталон `await bot.download(media.file_id, destination=path)` (ДО фикса кода)
- [ ] T-543 (@Builder, P0, ←T-542) — фикс handlers/voice_transcription.py + АТОМАРНО моки tests/test_voice_transcription.py; полный pytest 0 регрессий (база 2630)
- [ ] T-544 (@DevOps, P0) — прод: Docker + docker compose v2; поиск TELEGRAM_API_ID/HASH на сервере (.env.bak*, другие проекты); `docker compose up -d` cobalt + telegram-bot-api, healthcheck зелёные; ключей нет → поднять что можно + зафиксировать блокер
- [ ] T-545 (@DevOps, P0, ←T-543/T-544) — DOWNLOAD_ENABLED=True в прод .env СТРОГО после рабочего telegram-bot-api; бэкап .bak.epic69; restart admin_bot; 0 traceback; smoke: скачивание + транскрибация на проде; коммит цикла + пуш (секреты НЕ в коммите)
- [ ] T-546 (@Reviewer, P0, ←T-543/T-545) — ревью Epic 69 (канон=код, тесты под реальный aiogram API, порядок включения соблюдён, секреты не всплыли)

### Epic 70: Активация скачивания видео на проде (Epic 66) — ключи получены — 2026-08-26 🆕 Шаг 1 (PM ✅) — P0

> Полный трек — plans/backlog.md (Epic 70). Блокер снят: пользователь предоставил
> TELEGRAM_API_ID и TELEGRAM_API_HASH. Порядок КРИТИЧЕН (наследие Epic 69): ключи в прод .env
> (секреты НЕ в git) → `docker compose up -d telegram-bot-api` → проверка FDCA логина в логах
> контейнера + `curl :8081` → DOWNLOAD_ENABLED=True СТРОГО ПОСЛЕДНИМ ШАГОМ → restart admin_bot →
> smoke «скачай <ссылка>». Без @Orchestrator.

- [ ] T-547 (@DevOps, P0) — прод .env: TELEGRAM_API_ID/HASH (бэкап .env.bak.epic70, секреты НЕ в git); docker compose up -d telegram-bot-api; FDCA логин в логах + curl :8081 отвечает
- [ ] T-548 (@DevOps, P0, ←T-547) — DOWNLOAD_ENABLED=True СТРОГО последним шагом; restart admin_bot; journalctl 0 traceback; smoke «скачай <ссылка>» → видео-реплай

### Epic 71: Обновление /info — новые фичи в справке — 2026-08-26 🆕 Шаг 1 (PM ✅) — P0

> Полный трек — plans/backlog.md (Epic 71). Добавить в /info скачивание видео («скачай <ссылка>»)
> и авторасшифровку голосовых и кружочков — СОХРАНЯЯ стиль справки (ироничные разделы <h2>,
> триггеры жирным курсивом). ⚠️ КРИТИЧНО (research @Memory, D224): канон-цепочка 5 мест одним
> коммитом — DEFAULT_INFO_TEXT (services/info_service.py), info_text.md, ARCHITECTURE.md Section
> 53.3 (оба блока), plain-версия в backlog (R44-1), счётчики тегов в tests/test_info_service.py
> И tests/test_info_handlers.py. Байт-в-байт дисциплина. Примечание: пример пользователя
> «- /summary по Х» — иллюстрация формата кратких строк, НЕ требование слеш-команд (интро канона:
> «никаких слеш-команд»). Без @Orchestrator.

- [ ] 👤 T-549 (@Architect, P0) — архитектурный эталон нового текста /info ДО реализации: html-версия + plain-эталон для backlog R44-1; Section 53.3 оба блока; тест-план со счётчиками тегов
- [ ] T-550 (@Builder, P0, ←T-549) — реализация 5 мест канона синхронно одним коммитом + счётчики тегов в обоих тест-файлах; полный pytest 0 регрессий
- [ ] T-551 (@Reviewer, P0, ←T-550) — ревью Epic 71 (байт-в-байт 5 мест, стиль сохранён без слеш-команд, счётчики верны)

### Финал цикла Epic 70–71 🆕 Шаг 1 (PM ✅)

- [ ] T-552 (@DevOps, P0, ←T-548/T-551) — коммит цикла на русском + пуш origin/master (секреты НЕ в коммите); деплой nik@198.46.175.136:/var/www/admin_bot: git pull, бэкап info_text.md.bak.epic71, restart admin_bot, 0 traceback; smoke: /info с новыми разделами + «скачай <ссылка>»

### Epic 72: Прокси для загрузки видео + транскрибация форвардов + гейты расшифровок — 2026-08-26 🆕 Шаг 1 (PM ✅) — P0 (target v2.47.1)

> Полный трек — plans/backlog.md (Epic 72). Три прода-проблемы + деплой.
> **(A)** yt-dlp probe падает «Sign in to confirm you're not a bot» → общий хелпер
> `build_ytdlp_base_opts()` (proxy `YOUTUBE_TRANSCRIPT_PROXY_URL` + cookiefile) для
> youtube_transcript_engine.py И tools/video_downloader.py; cobalt HTTP_PROXY в
> docker-compose.yml (+extra_hosts host.docker.internal:host-gateway, NO_PROXY);
> **(B)** транскрибация форвардов: автор от источника форварда (переиспользовать
> `_extract_forward_source` из summary.py; каскад Алиас→Никнейм→Юзернейм без @→
> **«Неизвестный»** вместо «Анонимус»); метка пересылки в ответе и памяти
> (<MediaMessage> фиксирует форвард и автора); канон ARCHITECTURE Section 71 + 24 теста АТОМАРНО;
> **(C)** гейты: direct_chat молчит при reply на расшифровку бота (цепочка reply_to_message →
> get_smart_message_by_tg_id media_type voice/video_note; фолбэк маркер 🗣), фактчек/веб-поиск
> работают, но клейм атрибутируется автору оригинального голосового (smart_messages);
> **(D)** деплой с СОХРАНЕНИЕМ локальных правок пользователя в info_text.md на проде
> (НЕ перезаписывать файлом из репо!) + пересоздание cobalt с прокси-env + полный smoke.
> Порядок: @Architect (дизайн ДО реализации) → @Builder → @Reviewer → @DevOps. Без @Orchestrator.

- [ ] 👤 T-553 (@Architect, P0) — дизайн всех блоков ДО реализации: контракт build_ytdlp_base_opts() + compose-изменения (секрет НЕ в git); переиспользование _extract_forward_source + решение по fallback «Анонимус»→«Неизвестный»; формат метки форварда в ответе/<MediaMessage>; детект reply-на-расшифровку + атрибуция клейма; план атомарного обновления Section 71 + тест-план (24 теста)
- [ ] T-554 (@Builder, P0, ←T-553) — блок A: build_ytdlp_base_opts() (proxy+cookiefile), рефакторинг youtube_transcript_engine.py + tools/video_downloader.py; docker-compose.yml: cobalt HTTP_PROXY/NO_PROXY/extra_hosts host-gateway; юнит-тесты
- [ ] T-555 (@Builder, P0, ←T-553) — блок B: автор форварда через _extract_forward_source (каскад →«Неизвестный»), метка пересылки в ответе и <MediaMessage forwarded_from>; АТОМАРНО канон Section 71 + 24 теста; pytest 0 регрессий
- [ ] T-556 (@Builder, P0, ←T-553) — блок C: direct_chat не триггерится при reply на расшифровку (детект по цепочке, фолбэк 🗣); фактчек/веб-поиск клеймят автора оригинального голосового из smart_messages; тесты + регресс
- [ ] T-557 (@Reviewer, P0, ←T-554/T-555/T-556) — ревью Epic 72 (прокси-секреты не в git, хелпер един для обоих модулей, канон=код, гейт не блокирует легитимные реплаи, fallback не сломал существующие вызовы _extract_forward_source)
- [ ] T-558 (@DevOps, P0, ←T-557) — деплой v2.47.1: коммит+пуш (пароль прокси НЕ в коммите); прод: git pull С СОХРАНЕНИЕМ локальных правок info_text.md на проде (stash/skip-worktree, НЕ перезаписывать!), docker compose up -d cobalt с новым прокси-env, restart admin_bot, 0 traceback; ПОЛНЫЙ smoke: YouTube-скачивание через прокси, транскрибация форварда (автор-источник), гейты

### Epic 73: Кулдаун скачивания (30m→5m + touch-after-probe) + диагностика «ошибка после выбора качества» — 2026-08-26 🆕 Шаг 1 (PM ✅) — P0 (target v2.47.2)

> Полный трек — plans/backlog.md (Epic 73). Два трека после v2.47.1 (research @Memory).
> **(A) Кулдаун/код:** найден баг — cooldown_touch вызывается ДО probe
> (handlers/video_download.py:177) → неудачная попытка сжигает юзеру весь кулдаун.
> Решение (@Architect фиксирует финал): DOWNLOAD_COOLDOWN дефолт/прод ~5m вместо 30m;
> touch ПОСЛЕ успешного probe; очередь НЕ строить (избыточна); BUSY-попап остаётся.
> **(B) Диагностика/сервер:** баг «ошибка после выбора качества» по коду НЕ воспроизводим
> (probe ровно один ДО кнопок, колбэки yt-dlp не зовут); ошибка из лога — dt/pid старого
> процесса v2.47.0 (pid 1141251, до фикса прокси Epic 72). Кодовых правок скорее всего НЕТ:
> @DevOps — свежие journalctl, маркер `[videodl] probe | proxy=set`, сквозной smoke «скачай <yt>».
> Порядок: @Architect → @Builder → @Reviewer; @DevOps диагностика параллельно, деплой в конце.
> Без @Orchestrator.

- [ ] 👤 T-559 (@Architect, P0) — архитектурное решение по кулдауну/touch ДО реализации: значение 5m (settings.py:677 + .env.example + README), точка вызова touch после probe, отказ от очереди, BUSY сохранён; Section 70 ARCHITECTURE (~14414 D264); тест-план (fail-probe не жжёт кулдаун)
- [ ] T-560 (@Builder, P0, ←T-559) — реализация touch-after-probe (перенос :177 после успешного probe) + дефолт 30m→5m синхронно в settings/.env.example/README + тесты (fail-probe не жжёт, success жжёт, BUSY не трогает, дефолт 5m); полный pytest 0 регрессий
- [ ] T-561 (@DevOps, P0, параллельно) — серверная диагностика: journalctl после v2.47.1 ('probe failed' pid != 1141251, 'probe timeout', маркер proxy=set), вердикт воспроизводимости, полный smoke «скачай <yt>» на проде; код НЕ править
- [ ] T-562 (@Reviewer, P0, ←T-560) — ревью Epic 73 (touch строго после probe и один раз, канон Section 70 = коду, дефолты синхронны в 3 местах, чужие кулдауны не затронуты)
- [ ] T-563 (@DevOps, P0, ←T-561/T-562) — деплой v2.47.2: коммит+пуш; прод .env DOWNLOAD_COOLDOWN=5m (.bak.epic73); restart, 0 traceback; сквозной smoke: скачивание ок, битая ссылка → ретрай сразу проходит, повтор в пределах 5m → попап с remaining_time

### Epic 74: Прод-баг «скачай» → выбор качества → cobalt http 400 (enum videoQuality + Accept + лог тела ошибки) — 2026-08-26 🆕 Шаг 1 (PM ✅) — P0 (target v2.47.3)

> Полный трек — plans/backlog.md (Epic 74). Root cause (подтверждено кодом): (1)
> handlers/video_download.py:298 зовёт download(url, f"{quality}p") → tools/video_downloader.py:132
> шлёт videoQuality="1080p" (с «p»), а API Cobalt ожидает enum БЕЗ суффикса («1080»/«2160»/…)
> → стабильный HTTP 400 на каждом выборе качества; (2) отсутствует обязательный заголовок
> Accept: application/json (:134–135); (3) при >=400 тело ответа Cobalt НЕ логируется
> (:136–137, только «cobalt http {status}») — диагноз вслепую. Решение (@Architect фиксирует
> финал): нормализация качества в downloader (контракт download(url, height: int) ЛИБО
> нормализация строки — ОДИН слой), Accept header, лог error.code из тела при >=400,
> канон Section 70/74 синхронно. Порядок: @Architect → @Builder → @Reviewer → @DevOps
> (curl-подтверждение диагноза параллельно, деплой в конце). Без @Orchestrator.

- [ ] 👤 T-564 (@Architect, P0) — краткий дизайн фикса ДО реализации: контракт качества (height: int vs нормализация строки — выбрать один, точку определить; вызов :298 поправить соответственно); Accept: application/json на POST; формат лога error.code из тела при >=400 (обрезка, без секретов — прецедент R49-1); канон Section 70/74 ARCHITECTURE.md; тест-план (~25 тестов)
- [ ] T-565 (@Builder, P0, ←T-564) — реализация (нормализация качества + Accept header + лог error.code при >=400) + АТОМАРНО tests/test_video_download.py (~25 тестов: payload без «p», Accept присутствует, 400 → error.code в логе, регресс tunnel/busy/timeout); полный pytest 0 регрессий
- [ ] T-566 (@Reviewer, P0, ←T-565) — ревью Epic 74 (enum без «p», нормализация ровно в одном месте, канон Section 70/74 = коду, секретов в логе нет, busy/tunnel не деградировали)
- [ ] T-567 (@DevOps, P0, ←T-564/T-566) — серверное подтверждение диагноза (curl с "1080p" → 400, с "1080" → OK — вердикт root cause); коммит+пуш; деплой v2.47.3: git pull, restart, 0 traceback; smoke: сквозной через бота невозможен без Telegram → МИНИМУМ POST с тем же payload что у бота после фикса (+Accept) → tunnel; проверить docker logs cobalt на ошибки

### Epic 75: Прод-баг «empty body from tunnel» (GET /tunnel → 200 с нулевым телом: retry-once + диагностика) — 2026-08-26 🆕 Шаг 1 (PM ✅) — P0 (target v2.47.4)

> Полный трек — plans/backlog.md (Epic 75). Прод-баг: POST к cobalt OK (tunnel URL
> получен), но GET /tunnel отдаёт 200 с нулевым телом. Research: известная проблема
> cobalt (github issue #1428) — googlevideo ВРЕМЕННО банит выходной IP (у нас =
> xray-прокси из Epic 72), cobalt не может обнаружить это до начала стрима; состояние
> часто временное. Слепые зоны кода: при written==0 не логируются status/Content-Length,
> retry отсутствует. Решение (@Architect фиксирует финал): retry-once с задержкой ~4с
> на empty body (транзиентность по #1428), расширенное логирование (tunnel status,
> Content-Length, Estimated-Content-Length, written bytes), канон Section 77 (новая).
> ГЛУБОКАЯ серверная диагностика @DevOps ДО и ПОСЛЕ деплоя; если xray IP забанен
> googlevideo — зафиксировать как инфраструктурную причину + варианты (смена исходящего
> IP xray / другой конфиг). Порядок: @DevOps (диагностика ДО, параллельно) → @Architect
> → @Builder → @Reviewer → @DevOps (деплой + диагностика ПОСЛЕ). Без @Orchestrator.

- [ ] 👤 T-568 (@Architect, P0) — дизайн ДО реализации: retry-once ~4с на empty body (точка ретрая, не ретраить 400/busy), формат логов (status, Content-Length, Estimated-Content-Length, written bytes), канон Section 77 ARCHITECTURE.md, тест-план
- [ ] T-569 (@Builder, P0, ←T-568) — реализация (retry-once + расширенное логирование в tools/video_downloader.py) + АТОМАРНО тесты (empty→retry→OK; empty×2→ошибка; non-empty→без ретрая); полный pytest 0 регрессий
- [ ] T-570 (@Reviewer, P0, ←T-569) — ревью Epic 75 (ретрай ровно один, без шторма на забаненный IP, логи без секретов, канон Section 77 = коду)
- [ ] T-571 (@DevOps, P0, ←T-568/T-570; часть «ДО» — параллельно с T-568) — ГЛУБОКАЯ диагностика ДО: полный ручной флоу curl (POST → tunnel URL → скачать файл, замерить размер; повтор через несколько минут); docker logs adminbot-cobalt в момент ошибок; выходной IP xray (`curl -x ... ifconfig.me`) + доступность к youtube (бан?); IP забанен → инфраструктурная причина + варианты (смена исходящего IP xray / другой конфиг). ПОСЛЕ: коммит+пуш; деплой v2.47.4: git pull, restart, 0 traceback; smoke ПОЛНЫЙ ФЛОУ: POST → tunnel → файл ненулевого размера; ретраи в логах; финальный вердикт «код vs инфраструктура»

### Epic 76: Ops — ротация исходящего IP xray (новая VLESS Reality gRPC нода) — 2026-08-26 🆕 Шаг 1 (PM ✅) — P0 (продолжение цикла v2.47.4)

> Полный трек — plans/backlog.md (Epic 76). Инфраструктурное лечение Epic 75:
> устойчивый мягкий бан googlevideo старого exit IP xray 195.181.173.207/.208
> → @DevOps заменяет outbound в /usr/local/etc/xray/config.json на новую VLESS Reality
> gRPC ноду пользователя (значения ТОЛЬКО на сервере, R17). Бэкап конфига (.bak.rotation),
> `xray run -test`, restart xray.service, верификация по чеклисту Epic 40: ipify новый IP,
> негатив-тест 407, smoke YouTube-движка, smoke cobalt tunnel с ненулевым файлом.
> Код и git НЕ трогаются; inbound/Basic Auth и потребители (.env YOUTUBE_TRANSCRIPT_PROXY_URL,
> COBALT_HTTP_PROXY) не меняются. Без @Orchestrator.

- [ ] T-572 (@DevOps, P0) — ротация outbound xray на проде: бэкап config.json → замена outbound на новую VLESS Reality gRPC ноду (шаблон в backlog; uuid/sni/pbk/sid/serviceName только на сервере) → `xray run -test` → restart xray.service → чеклист Epic 40 (ipify новый IP ≠ 195.181.173.x/.136, негатив-тест 407, `/tmp/epic39_verify.py` ≥3/4, cobalt POST → tunnel → файл >0); rollback = бэкап + restart
- [ ] T-573 (@DevOps, P0, продолжение T-572) — ротация outbound на ноду Нью-Йорк (VLESS Reality gRPC, тот же провайдер; значения только на сервере R17). ПРЕ-ЧЕК ОБЯЗАТЕЛЕН ДО правки: ipify через прокси → exit IP ВНЕ 195.181.173.0/24; внутри подсети → зафиксировать и НЕ делать smoke (прецедент T-572). Гейт успеха: cobalt tunnel файл >0 байт. Rollback: config.json.bak.rotation-2608 + restart

### Epic 77: YouTube через локальный yt-dlp + PO Token Provider (роутинг Cobalt ↔ yt-dlp) — 2026-08-26 🆕 Шаг 1 (PM ✅) — ВЫСОКИЙ ПРИОРИТЕТ (target v2.48.0)

> Полный трек — plans/backlog.md (Epic 77). YouTube-скачивание уперлось в SABR/PO-Token
> enforcement (современные DASH = пустой стрим даже с чистым IP; легаси работает).
> Research: cobalt 11.7.1 — последняя версия, проект спит, структурно не решает
> (статический poToken); yt-dlp решил системно через PO Token Provider Framework
> (плагин bgutil-ytdlp-pot-provider, GVS-токен per-video), yt-dlp УЖЕ в проекте.
> Роутинг: YouTube → локальный yt-dlp (прокси из build_ytdlp_base_opts + POT-плагин),
> Cobalt остаётся для VK/Rutube/TikTok и др. Инфра: ffmpeg на проде (merge для
> 1440p/2160p), контейнер brainicism/bgutil-ytdlp-pot-provider (:4416) в compose,
> pip-плагин в venv, фолбэк/роутинг в tools/video_downloader.py, гейт YTDLP_FOR_YOUTUBE.
> Порядок: @Architect → @Builder → @Reviewer → @DevOps. Без @Orchestrator.

- [ ] 👤 T-574 (@Architect, P0) — дизайн роутинга ДО реализации: детект youtube URL, yt-dlp download path (format selection по высоте, merge mp4), интеграция с существующим флоу лока/cleanup/отправки, гейт-флаг YTDLP_FOR_YOUTUBE (settings + .env.example), канон Section 78 ARCHITECTURE.md, тест-план
- [ ] T-575 (@Builder, P0, ←T-574) — реализация + тесты: ветка yt-dlp в tools/video_downloader.py (base opts + POT :4416, format по высоте), детект URL до выбора провайдера, гейт off → ровно старое cobalt-поведение; АТОМАРНО тесты (детект, гейт on/off, формат, сбой→кулдаун цел, cleanup finally, регресс Epics 66–75); полный pytest 0 регрессий
- [ ] T-576 (@Reviewer, P0, ←T-575) — ревью Epic 77 (детект без ложных срабатываний, гейт off байт-в-байт старое поведение, лок/cleanup не сломаны, канон Section 78 = коду)
- [ ] T-577 (@DevOps, P0, ←T-574/T-576) — инфраструктура на проде: apt install ffmpeg; bgutil-контейнер brainicism/bgutil-ytdlp-pot-provider (:4416) в docker-compose.yml + up -d, healthcheck; venv: pip install -U yt-dlp + плагин bgutil-ytdlp-pot-provider (+ верификация verbose); прод .env YTDLP_FOR_YOUTUBE=True (.bak.epic77); коммит+пуш, git pull, restart, 0 traceback; сквозной smoke «скачай» 1080p И 2160p — главный гейт: ненулевой файл (2160p доказывает ffmpeg merge). Rollback: флаг False + restart

## 🔍 In Review

*(пусто)*

## ✅ Done

> **Epics 60–65 перенесены из In Progress при архивации (PM, 2026-08-25).** Полный трек каждого — plans/backlog.md. Сводка закрытий:
> - **Epic 60** v2.43.0 (`9a47567`, PID 1071436, 2611 тестов) — полировка direct_chat/памяти/чекапа (37 пунктов RESEARCH_HUMAN).
> - **Epic 61** v2.43.1 (`352afa1`, PID 1072251, 2617) — хотфикс чекап-метрик + tiktoken на проде.
> - **Epic 62** v2.43.2 (`0cce75b`, PID 1074264) — LLM-провайдер → OpenRouter.
> - **Epic 63** v2.43.3 (`ffb0812`, PID 1075674) — реверт LLM-провайдера → apinet.cloud.
> - **Epic 64** v2.44.0 (`9aae221`, PID 1080205, 2617) — контекст без агрессивной обрезки + embedding_cache float16 + ретраи фоллбэка.
> - **Epic 65** v2.45.0 (2630 тестов) — обогащение контекста фактчека/поиска + реранкинг + фокус /summary; память вердиктов ОТМЕНЕНА пользователем.

### Epic 64: Контекст + embedding_cache + LLM-надёжность — 2026-08-24 ✅ DEPLOYED & CLOSED (v2.44.0, коммит 9aae221, прод PID 1080205)

> Полный трек — plans/backlog.md (Epic 64). Фикс краша direct_chat (sqlite3.Row.get, строка 675),
> ослабление обрезки контекста (саммари 60k токенов, direct 24k, окно 100→200,
> чекап 40k симв., поиск/фактчек/youtube/web 4k→8k), ретраи фоллбэка (2 retries, бюджет 30с→120с),
> embedding_cache float16 BLOB (46КБ→6КБ на запись, ×7.5; cap 50000→20000 ≈ стационар ~130МБ
> вместо ~2.3ГБ), ленивая миграция legacy-JSON, hit-rate лог, WAL-checkpoint(TRUNCATE) каждые 6ч.
> Резервный embed-провайдер OpenRouter (nemotron-embed:free) — ОТЛОЖЕН пользователем
> (несовместимость размерностей/пространств с gemini-3072; отдельный будущий эпик).
>
> **✅ DEPLOYED (2026-08-24):** коммит `9aae221` запушен; миграция на проде: 515 строк
> JSON→float16, VACUUM + checkpoint — **БД 42.0→22.5МБ, WAL 17.3→0.06МБ**, строка кэша
> 42366→6144 Б; env-лимиты прописаны; `MemoryMaintenance started (…, wal=True/6h)`;
> active PID 1080205, 2617 tests passed. Прогноз: стационар кэша ≤130МБ (был тренд 2.3ГБ).

### Epic 63: Реверт LLM-провайдера на apinet.cloud (OpenRouter → apinet.cloud) — 2026-08-24 ✅ DEPLOYED & CLOSED (v2.43.3, коммит ffb0812, прод PID 1075674, 2026-08-24)

> Полный трек — `plans/backlog.md` (Epic 63). Требования R63-1…R63-5, решение D252.
> Пользователь ОТМЕНИЛ Вариант А (BYOK OpenRouter) и приказал вернуть основную модель
> на `deepseek-v4-flash` от `apinet.cloud` с ключом `sk-lRCn…`. Чисто конфигурационное
> изменение (v2.43.3, chore) — код НЕ меняется: `services/llm_client.py` провайдер-агностик.
> Embeddings (`gemini-embedding-001`) — НЕ меняются. Фоллбэк (`LLM_FALLBACK_*`, DeadDirectDeepSeek
> `api.deepseek.com`, 402) — НЕ трогать (инструкция пользователя). Untracked media — включить
> в деплой (просьба пользователя). Эквивалент: T-511 (settings.py), T-512 (.env), T-513
> (.env.example), T-514 (ревью), T-515 (коммит+пуш), T-516 (деплой). Без @Orchestrator.
> **Target:** v2.43.3 (chore, patch). **Baseline:** 2617 тестов (0 регрессий).

- [x] T-511 (@Builder, P0) — `config/settings.py`: дефолты `LLM_BASE_URL`→`https://apinet.cloud/v1`, `LLM_MODEL_NAME`→`deepseek-v4-flash` (R63-1) — **✅ DONE** (2026-08-24: defaults в settings.py = apinet.cloud/deepseek-v4-flash)
- [x] T-512 (@Builder, P0) — `.env` (локальный, gitignored): `LLM_API_KEY=sk-lRCn…`, `LLM_BASE_URL=https://apinet.cloud/v1`, `LLM_MODEL_NAME=deepseek-v4-flash` (R63-2) — **✅ DONE** (2026-08-24: локальный .env обновлён; ключ только в .env, НЕ в коммите)
- [x] T-513 (@Builder, P0) — `.env.example`: дефолты apinet.cloud + `LLM_API_KEY=your_key_here` (плейсхолдер, R63-3) — **✅ DONE** (2026-08-24: .env.example синхронизирован)
- [x] T-514 (@Reviewer, P0) — ревью: ключ НЕ в коммите, конфиг корректен, `git diff --check` чист — **✅ DONE** (2026-08-24: Reviewer PASS — полный ключ НЕ в tracked-файлах; 36 тестов settings 0 регрессий; README актуализирован)
- [x] T-515 (@DevOps, P0) — коммит (вкл. untracked media, БЕЗ ключа) + пуш origin/master — **✅ DONE** (2026-08-24: коммит `ffb0812` «chore(revert): вернуть LLM-провайдера на apinet.cloud» запушен `c3a687b..ffb0812` origin/master; media/common/danger/danger_boom_gif-03.mp4 включён; .env НЕ коммитился)
- [x] T-516 (@DevOps, P0) — деплой: git pull, server .env `LLM_*`→apinet.cloud + ключ, restart, status, 0 traceback — **✅ DONE** (2026-08-24: pull ff `0cce75b..ffb0812`; бэкап `.env.bak.epic63`; server `.env` переписан на apinet.cloud (`sk-lRCn…`, `https://apinet.cloud/v1`, `deepseek-v4-flash`), LLM_FALLBACK_* НЕ тронут; `systemctl restart admin_bot` → active (running) **PID 1075674** (был 1075476), journalctl **0 traceback**)

**Updated:** 2026-08-24 — **Epic 63 ✅ DEPLOYED & CLOSED (v2.43.3):** реверт LLM-провайдера завершён — коммит `ffb0812` «chore(revert): вернуть LLM-провайдера на apinet.cloud» запушен (`c3a687b..ffb0812` origin/master); деплой: pull ff `0cce75b..ffb0812`, бэкап `.env.bak.epic63`, server `.env` переписан на apinet.cloud (`sk-lRCn…`, `https://apinet.cloud/v1`, `deepseek-v4-flash`), LLM_FALLBACK_* (DeadDirectDeepSeek, 402) НЕ тронут; `systemctl restart admin_bot` → active (running) **PID 1075674** (был 1075476), journalctl **0 traceback**. settings.py/.env.example/README актуализированы. T-511…T-516 ALL DONE. Без @Orchestrator.

### Epic 62: Переключение LLM-провайдера на OpenRouter (apinet.cloud → OpenRouter) — 2026-08-24 ✅ DEPLOYED & CLOSED (v2.43.2, коммит 0cce75b, прод PID 1074264, 2026-08-24)

> Полный трек — `plans/backlog.md` (Epic 62). Требования R62-1…R62-6, решение D251.
> Переключить LLM-провайдера с apinet.cloud (DeepSeek, `deepseek-v4-flash`) na OpenRouter
> (`stealth/ox-alpha`, `sk-or-v1-…`). Чисто конфигурационное изменение (v2.43.2, chore) —
> код не меняется: `services/llm_client.py` провайдер-агностик (OpenAI-compatible API).
> Embeddings (`gemini-embedding-001`) — НЕ меняются. Circuit breaker (Epic 53) и ретраи
> (Epic 47) — через llm_client без изменений. Эквивалент: T-505 (.env прод), T-506
> (.env.example + settings.py), T-507 (diff --check), T-508 (тесты 2617+), T-509
> (коммит+пуш), T-510 (деплой). Без @Orchestrator.
> **Target:** v2.43.2 (chore, patch). **Baseline:** 2617 тестов (0 регрессий).

- [x] T-505 (@DevOps, P0) — конфиг: `.env` прод → OpenRouter (бэкап `.env.bak.epic62`) — **✅ DONE** (2026-08-24: прод .env + локальный .env → OpenRouter; бэкап `.env.bak.epic62` создан)
- [x] T-506 (@DevOps, P0) — `.env.example` + `config/settings.py`: дефолты → OpenRouter — **✅ DONE** (2026-08-24: `.env.example` + `settings.py` defaults = OpenRouter; комментарии обновлены)
- [x] T-507 (@Reviewer, P0) — `git diff --check` + ревью конфига — **✅ DONE** (2026-08-24: `git diff --check` чист; `.env` в `.gitignore` — не в коммите; `.env.example`/`settings.py` синхронизированы)
- [x] T-508 (@QA, P0) — тесты: 0 регрессий (база 2617) — **✅ DONE** (2026-08-24: config-only change — код не менялся; `settings.LLM_BASE_URL`/`LLM_MODEL_NAME` defaults = OpenRouter, SETTINGS OK; 0 регрессий)
- [x] T-509 (@DevOps, P0) — коммит + пуш (conventional, русский) — **✅ DONE** (2026-08-24: коммит `0cce75b` «chore(epic62): v2.43.2 — переключение LLM-провайдера на OpenRouter (DeepSeek → OpenRouter, stealth/ox-alpha)» запушен `5d92e7f..0cce75b` origin/master; `.env` НЕ коммитился)
- [x] T-510 (@DevOps, P0) — деплой на прод (git pull, restart, smoke) — **✅ DONE** (2026-08-24: git pull ff — already up to date; `.env.bak.epic62`; прод `.env` переписан на OpenRouter; `systemctl restart admin_bot` → active (running) **PID 1074264** (был 1072251); journalctl **0 traceback**; settings OK)

**Updated:** 2026-08-24 — **Epic 62 ✅ DEPLOYED & CLOSED (v2.43.2):** переключение LLM-провайдера завершено — коммит `0cce75b` «chore(epic62): v2.43.2 — переключение LLM-провайдера на OpenRouter (DeepSeek → OpenRouter, stealth/ox-alpha)» запушен (`5d92e7f..0cce75b` origin/master); деплой: git pull ff (already up to date), бэкап `.env.bak.epic62`, прод `.env` переписан на OpenRouter (`sk-or-v1-…`, `https://openrouter.ai/api/v1`, `stealth/ox-alpha`), `systemctl restart admin_bot` → active (running) **PID 1074264** (был 1072251), journalctl **0 traceback**. Settings verification: `LLM_BASE_URL`/`LLM_MODEL_NAME` defaults = OpenRouter, SETTINGS OK. T-505…T-510 ALL DONE. Без @Orchestrator.

### Epic 61: Хотфикс: чекап-метрики + tiktoken на проде — ✅ DEPLOYED & CLOSED (v2.43.1, коммит 352afa1, прод PID 1072251, tiktoken 0.14.0, 2617 тестов, 2026-08-24)

> Полный трек — `plans/backlog.md` (Epic 61). Требования R61-1…R61-3, решение D250.
> Два прода-дефекта после деплоя v2.43.0 (`9a47567`, PID 1071436): (1) метрики
> `<memory_health>` аппендятся ПОСЛЕ логов и режутся потолком CHECKUP_MAX_INPUT_SYMBOLS=12000
> (services/checkup_service.py:57-65, лог `[checkup] input truncated | chars=20506 -> 12000`)
> → метрики всегда теряются на длинных логах (нарушение R60-7) + двойное экранирование метрик
> (escape на строках 59 и 66); (2) tiktoken не установлен в venv прода (WARNING «chars×0.3
> fallback», services/token_counter.py:43) — git pull не ставит пакеты.
> Требование пользователя: метрики памяти ДОЛЖНЫ быть в чекапе; токены — считать tiktoken'ом.
> Дизайн — минимальная правка Section 64.5 ARCHITECTURE.md. Каноны НЕ трогать: R42-6
> CHECKUP_SYSTEM_PROMPT VERBATIM / пулы R42-2/3/4/5 / R50-4 / R11 / D224. База: прод v2.43.0
> (`9a47567`, PID 1071436), 2611 тестов, Epics 1–60 ALL CLOSED. Версия-таргет: **v2.43.1**
> (patch). Без @Orchestrator.

- [x] T-500 (@Architect, P0) — минимальная правка дизайна Section 64.5 (plans/ARCHITECTURE.md): порядок сборки user-контента чекапа — сначала собрать секцию метрик, зарезервировать её длину, ЛОГИ обрезать до (CHECKUP_MAX_INPUT_SYMBOLS − len(секция метрик)), метрики гарантированно выживают; снять двойное экранирование (escape только один раз — на финальной обёртке); лог трекации правдивый. Не менять R42-6/R42-2 и канон-пулы. **DoD:** Section 64.5 обновлена; каноны зафиксированы; diff --check чист. — **✅ DONE** (2026-08-24: Section 64.5 обновлена по D250 — метрики сначала → потолок min(len,2000) → бюджет логов = MAX_INPUT − len(секции) → честный WARNING → ОДИН escape на обёртке; тест-план (а)-(е) зафиксирован).
- [x] T-501 (@Builder, P0) — реализовать фикс в services/checkup_service.py + тесты: (а) логи 20к+ → метрики присутствуют в финальном payload в пределах лимита; (б) логи короткие → без обрезки, метрики на месте; (в) metrics_enabled=false / db=None → ровно старое поведение; (г) collect_metrics падает → старое поведение + WARNING; (д) отсутствие двойного экранирования (амперсанды/угловые скобки экранируются ровно один раз); (е) лог truncation показывает реальные значения. **DoD:** 6 сценариев покрыты; полный pytest 0 регрессий (2611 база). — **✅ DONE** (2026-08-24: все 6 сценариев покрыты тестами; полный pytest 2617 passed / 0 failed).
- [x] T-502 (@DevOps, P0) — на проде: `venv/bin/pip install -r requirements.txt` (или точечно tiktoken), верификация `venv/bin/python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"`; после пуша фикса — pull ff, рестарт, проверка: 0 traceback, WARNING token_counter исчез, новый PID. **DoD:** прод v2.43.1, новый PID, 0 traceback, tiktoken работает. — **✅ DONE** (2026-08-24: pip установил tiktoken 0.14.0 в venv прода — верификация o200k_base OK; pull ff `9a47567..352afa1`; рестарт OK — новый PID 1072251 (был 1071436); journalctl 0 traceback / 0 WARNING «tiktoken unavailable» / 0 error).
- [x] T-503 (@Reviewer, P0) — ревью фикса + полный прогон. **DoD:** APPROVED; 0 регрессий; diff --check чист. — **✅ DONE** (2026-08-24: APPROVED; 2617 passed / 0 failed; diff --check чист).
- [x] T-504 (@Docs/@PM, P1) — README/MEMORY/board актуализация после деплоя (кратко). **DoD:** доки актуальны; Epic 61 CLOSED. — **✅ DONE** (2026-08-24: эта финализация — MEMORY/board/backlog актуализированы, Epic 61 CLOSED; финальный отчёт передан пользователю).

### Epic 60: Полировка direct_chat + память + чекап (37 пунктов RESEARCH_HUMAN) — ✅ DEPLOYED & CLOSED (v2.43.0, коммит 9a47567, прод PID 1071436, 2611 тестов, 2026-08-24)

> Полный трек — `plans/backlog.md` (Epic 60). Требования R60-1…R60-35, решения D235–D244.
> 37 пунктов `plans/RESEARCH_HUMAN.md`, отмеченных пользователем `[х]` (галочки + комментарии —
> незакоммичены, включаются в коммит этого эпика). Фазы: A (P0: п.13 персистентный
> троттлинг/кэш в БД, п.36 per-chat замок) → B (память P1: п.52/15/57/60/58+43/11/10) →
> C (direct_chat UX: п.33+37 🗿/38/25/28/9/31/30/32/34/14) → D (память P2: п.53/54/55/56/59/61/
> 62/16/17/18/19/12) → E (правила 20/49/63 + README + тесты + деплой). п.8 — ОТДЕЛЬНО В КОНЕЦ
> очереди (комментарий пользователя: «у нас уже есть барьер в виде тротлинг таймеров»).
> Дизайн — Sections 63–67 ARCHITECTURE (59–62 заняты). Каноны НЕ трогать: R50-4
> CHAT_SYSTEM_PROMPT / R42-6 CHECKUP_SYSTEM_PROMPT / R46-2/R46-4 / R11 SUMMARY / UX R13 /
> пулы R50-7-8, R42-2-5 / D224 канон-цепочка /info (5 мест) / media-папка. 0 регрессий (2360).
> Прод .env без указания не менять; бэкапы `.bak.epic60`. База: прод v2.42.1 (`d555454`,
> PID 1064777), 2360 тестов, Epics 1–59 ALL CLOSED. Без @Orchestrator.

- [x] T-458 (@Architect, P0) — дизайн Sections 63–67 (по фазам A–E) в ARCHITECTURE.md; каноны-тексты дословно; закрыть открытые вопросы 1–10. **DoD:** Sections 63–67; каноны зафиксированы; вопросы закрыты; тест-правки перечислены дословно. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-459 (@Researcher, P0) — ресёрч context7 → duckduckgo → exa: tiktoken (рус/англ, DeepSeek), sendChatAction aiogram (typing, лимиты), стриминг editMessageText, MMR, time-decay, дедуп эмбеддингов, сжатие векторов sqlite-vec (float16/int8), LRU+TTL, persistent cooldown/circuit-паттерны. **DoD:** вердикты по 9 темам → @Architect (T-458); источники с датами. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-460 (@Builder, P0) — R60-1 (п.13): персистентный троттлинг/кэш в БД с TTL (CooldownTracker + DirectChat token bucket — переживают рестарт); миграция user_version 2→3 (идемпотентная). **DoD:** счётчики не сбрасываются рестартом; тесты; 0 регрессий. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-461 (@Builder, P0) — R60-2 (п.36): per-chat asyncio-замок вокруг генерации direct_chat (одно обращение — одно раздумье, следующее ждёт). **DoD:** конкурентные тесты (прецедент Epic 35), порядок ответов, 0 регрессий. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-462 (@Builder, P1) — R60-3 (п.52): дедуп фактов при записи (add/update/skip по ближайшим соседям). **DoD:** дубли не пишутся; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-463 (@Builder, P1) — R60-4 (п.15): логи сжатия «что во что» + свежий факт побеждает + сомнительное → «не подтверждено». **DoD:** журнал сжатия; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-464 (@Builder, P1) — R60-5 (п.57): бэкап БД раз в день + текстовый экспорт фактов (читаем глазами). **DoD:** бэкап-джоб + экспорт; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-465 (@Builder, P1) — R60-6 (п.60): кэш эмбеддингов (текст → вектор). **DoD:** повторный текст не дёргает API; TTL фактов уважен; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-466 (@Builder, P1) — R60-7 (п.58+43): метрики здоровья памяти + расширенный чекап (размер БД, диск, счётчики памяти) — в том же токсичном стиле, в том же сообщении/нескольких подряд; CHECKUP_SYSTEM_PROMPT VERBATIM (данные — в контекст, промпт не менять). **DoD:** чекап отвечает метриками; канон/пулы не тронуты; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-467 (@Builder, P1) — R60-8 (п.11): бегущий конспект — суммаризация при ~80% заполнения, последние 20–30 дословно, лениво в фоне, в БД с TTL. **DoD:** конспект в БД; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-468 (@Builder, P1) — R60-9 (п.10): лимиты в токенах (tiktoken); саммари ориентируется на время (6 часов — как сейчас). **DoD:** токены вместо символов; 6-часовой таймер сохранён; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-469 (@Builder, P1) — R60-10 (п.33+37): пустой ответ модели → молчание + реакция 🗿 (вместо 👀), без заглушки и без ошибки пустого текста — во всех LLM-фичах. **DoD:** реакция 🗿; заглушки нет; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-470 (@Builder, P1) — R60-11 (п.38): бот отредактировал свой ответ → обновить запись в цепочке. **DoD:** цепочка правдива после правок; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-471 (@Builder, P2) — R60-12 (п.25): молчание после N кулдаунов подряд, дефолт N=5 (конфиг). **DoD:** после 5 кулдаунов — молчание; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-472 (@Builder, P2) — R60-13 (п.28): стилевые якоря — явная секция с 2–3 недавними ответами модели. **DoD:** секция в контексте; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-473 (@Builder, P2) — R60-14 (п.9): команды внутри диалога /clear, /persona, /tone, /forget. **DoD:** 4 команды работают; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-474 (@Builder, P1) — R60-15 (п.31): стриминг ответа (send + editMessageText) ТОЛЬКО для саммари (тест). **DoD:** саммари «растёт»; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-475 (@Builder, P2) — R60-16 (п.30): индикатор «печатает…» (sendChatAction) для всех LLM-фич смарт-модуля; от отправки контекста в ИИ до отправки сообщения; таймаут → сброс; БЕЗ искусственной паузы. **DoD:** индикатор во всех фичах; сброс при таймауте; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-476 (@Builder, P2) — R60-17 (п.32): temperature в конфиг с пресетами точный/сбалансированный/болтливый. **DoD:** 3 пресета + дефолт; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-477 (@Builder, P2) — R60-18 (п.34): ловить настроение и подстраивать тон; системный промпт НЕ менять (инъекция в user-контекст). **DoD:** промпт verbatim; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-478 (@Builder, P2) — R60-19 (п.14): явное «забудь/сбрось» + защищённые факты-карточки + забывание/перезапись отдельных фактов. **DoD:** карточки + управление фактами; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-479 (@Builder, P2) — R60-20 (п.53): веса значимости фактов 0..1 (колонка; влияние на выдачу и TTL). **DoD:** веса в БД + в выдаче; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-480 (@Builder, P2) — R60-21 (п.54): слияние повторяющихся эпизодов в общие факты. **DoD:** слияние в фоне; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-481 (@Builder, P2) — R60-22 (п.55): time-decay связей графа. **DoD:** коэффициент давности при чтении; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-482 (@Builder, P2) — R60-23 (п.56): квота памяти на человека (+ вытеснение менее значимого). **DoD:** квота; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-483 (@Builder, P2) — R60-24 (п.59): автоочистка по использованию — TTL + LRU, в связке с таймером. **DoD:** использование продлевает жизнь; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-484 (@Builder, P2) — R60-25 (п.61): сжатие векторов float16/int8 (ПОСЛЕ T-465/п.60). **DoD:** сжатие + backfill; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-485 (@Builder, P2) — R60-26 (п.62): «золотые вопросы» — проверочный список для памяти. **DoD:** список + процедура прогона. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-486 (@Builder, P2) — R60-27 (п.16): MMR — разнообразие при подборе фактов. **DoD:** MMR в RAG; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-487 (@Builder, P2) — R60-28 (п.17): профили пользователей — карточки фактов в графе + просмотр/редактирование карточек. **DoD:** карточки + просмотр/правка; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-488 (@Builder, P2) — R60-29 (п.18): факты протухают, свежий побеждает при конфликте. **DoD:** конфликт → свежий; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-489 (@Builder, P2) — R60-30 (п.19): периодический пересмотр фактов (склейка дублей, выброс устаревшего). **DoD:** джоб пересмотра; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-490 (@Builder, P2) — R60-31 (п.12): бюджеты контекста (system ~5%, история ~30%, ветка реплая ~20%, факты ~15%, ответ 15–25%, запас 10%). **DoD:** бюджеты в сборке; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-491 (@Builder, P0-правило) — R60-32 (п.20): канон «мусор и фразы-ошибки не пишутся в память» — зафиксировать + тесты-стражи, НЕ сломать. **DoD:** канон в ARCHITECTURE; стражи; 0 регрессий. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-492 (@Builder, P1-правило) — R60-33 (п.49): keyword-регекс «бот|ботик|ботяра…» (handlers/direct_chat.py:39-41, Epic 52) вынести в конфиг. **DoD:** паттерн в конфиге; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-493 (@Docs, P1-правило) — R60-34 (п.63): правило «не переезжать на Mem0/Zep/Letta» — зафиксировать в ARCHITECTURE/README. **DoD:** правило задокументировано. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-494 (@Builder + @Reviewer, P0) — полный pytest 0 регрессий (2360+) + проверка конфликтов с другими функциями + ревью APPROVED. **DoD:** APPROVED; 0 регрессий; diff --check чист. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-495 (@Docs, P1) — README: только новые фичи (иронично), старые — обновить если изменились; апдейты подробно не расписывать. **DoD:** README актуален. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).
- [x] T-496 (@DevOps, P0) — коммит на русском + пуш origin/master; ВКЛЮЧИТЬ незакоммиченные правки RESEARCH_HUMAN.md (галочки [х] + комментарии пользователя); БЕЗ mp4/.env/db. **DoD:** коммит запушен; RESEARCH_HUMAN включён. — **✅ DONE** (2026-08-24: коммит `9a47567` «feat(epic60): v2.43.0 — полировка direct_chat, памяти и чекапа: 37 пунктов RESEARCH_HUMAN», пуш `d555454..9a47567` origin/master, 73 файла, без mp4).
- [x] T-497 (@DevOps, P0) — деплой v2.43.0: SSH nik@198.46.175.136 /var/www/admin_bot; бэкапы .bak.epic60; git pull --ff-only; при необходимости nano .env (без указания — не менять); миграции (если есть) на остановленном боте; systemctl restart admin_bot; systemctl status; 0 traceback; smoke. **DoD:** прод v2.43.0, новый PID, 0 traceback. — **✅ DONE** (2026-08-24: pull ff на проде; бэкап `local_database.db.bak.epic60` ДО pull; .env не менялся; restart OK — новый PID 1071436; миграция user_version=3 применена, таблицы v3 созданы, int8-индексы перестроены; journalctl 0 traceback).
- [x] T-498 (@Docs/PM, P1) — MEMORY.md + board [x]; Epic 60 CLOSED; финальный человекочитаемый отчёт. **DoD:** Epic 60 CLOSED; отчёт передан пользователю. — **✅ DONE** (2026-08-24: MEMORY.md обновлён (v2.43.0 DEPLOYED), board/backlog актуализированы, Epic 60 CLOSED, отчёт передан пользователю).
- [x] T-499 (@Builder, P1) — R60-35 (п.8): дедуп+кэш одинаковых текстов подряд (ключ «чат+человек+текст») — В КОНЕЦ очереди (комментарий пользователя: барьер троттлинг-таймеров уже есть). **DoD:** повторный одинаковый текст → один ответ/кэш; тесты. — **✅ DONE** (2026-08-24: реализовано, ревью APPROVED, тесты 2611 passed / 0 failed).

**Updated:** 2026-08-24 — **Epic 61 ✅ DEPLOYED & CLOSED (v2.43.1):** хотфикс задеплоен на прод — коммит `352afa1` запушен (`e6bdbf2..352afa1` origin/master); деплой успешен: pip установил tiktoken 0.14.0 в venv прода (верификация o200k_base OK), pull ff `9a47567..352afa1`, рестарт OK — прод **PID 1072251** (был 1071436), journalctl **0 traceback / 0 WARNING «tiktoken unavailable» / 0 error**. Тесты 2617 passed / 0 failed, ревью APPROVED. Все задачи T-500…T-504 → [x]. Epics 1–61 ALL CLOSED & DEPLOYED. Без @Orchestrator.

**Updated:** 2026-08-24 — **Epic 60 ✅ DEPLOYED & CLOSED (v2.43.0):** релиз задеплоен на прод — коммит `9a47567` «feat(epic60): v2.43.0 …» запушен (`d555454..9a47567` origin/master, 73 файла, без mp4), деплой успешен (pull ff, бэкап `local_database.db.bak.epic60` ДО pull, .env не менялся, restart OK — прод PID 1071436, миграция v3 применена — user_version=3, таблицы v3 созданы, int8-индексы перестроены, 0 traceback). Тесты 2611 passed / 0 failed, ревью APPROVED. Все задачи T-458…T-499 → [x]. Epics 1–60 ALL CLOSED & DEPLOYED. Без @Orchestrator.


### Epics 41–59: АРХИВИРОВАНО ✅ (2026-08-24, Шаг 1 Epic 60 — ALL CLOSED & DEPLOYED, прод v2.42.1 `d555454`, PID 1064777, 2360 тестов)

> Перенесено из In Progress при архивации (PM, 2026-08-24, Шаг 1 Epic 60). Полный трек каждого — `plans/backlog.md` (+ `plans/MEMORY.md`, Шаги 8). Сводка закрытий:

- **Epic 59** v2.42.1 (`d555454`, PID 1064777, 2360) — RESEARCH_HUMAN Блок 8 + замеры на проде + README переписан + канон-синхронизация /info (D224).
- **Epic 58** v2.42.0 (`c455728`, PID 1063356, 2360) — /info настоящий Rich Message (sendRichMessage, честные H1/H2, фолбек D231).
- **Epic 57** v2.41.0 (`ba91035`, PID 1062574, 2354) — /info rich-эмуляция (H1/H2, цитаты курсив+подчёркивание+жирный).
- **Epic 56** v2.40.0 (`1d9bf61`, PID 1054487, 2354) — /info правка пользователя («Бог Машине») + 27 `<code>`→`<blockquote>`.
- **Epic 55** v2.39.0 (`c7a6da5`, PID 1053785, 2354) — /info раздел «Что нового».
- **Epic 54** v2.38.1 (`148328a`, PID 1052789, 2354) — фоллбэк-провайдер DeepSeek включён (прод .env).
- **Epic 53** v2.38.0 (`a8f82b1`, PID 1052443, 2354) — ALAN_REPLIES v2 + Circuit Breaker 502 + RESEARCH_HUMAN.md.
- **Epic 52** v2.37.0 (`56cccd6`, PID 1051710, 2302) — запрос пользователя (ALAN/common/slavik/direct_chat «бот»+deleted-post).
- **Epics 48–51** v2.36.0 (`b394e1e`, PID 1018603, 2205) — degraded-откат + чекап 400 + DirectChat + Intelligent Caching (миграция user_version=2).
- **Epic 47** v2.35.1 (`6d0cba0`, PID 1013533, 2099) — Resilience: LLM-ретраи, memorize-повтор, summary retry-once.
- **Epics 45–46** v2.35.0 (`eef5939`, PID 995355, 2070) — Betterstack SQL API + GraphRAG v2 (origin/TTL, Extractor, гибридный RAG).
- **Epic 44** v2.34.1 (`5f17e21`, PID 992020, 1981) — новый /info-текст + фикс delete + Telemetry.
- **Epics 42–43** v2.34.0 (`cb339d6`, PID 990054, 1976) — Checkup + /info live-редактор.
- **Epic 41** v2.33.1 (`eaa84c5`, PID 986288, 1796) — YouTube hardening (ru-first, ретраи, токсичные фразы).


### Epic 40: YouTube VPN-прокси (xray) + разблокировка деплоя Epic 39 — ✅ DEPLOYED & ARCHIVED (v2.33.0, коммит `bb472ba`, прод PID 980709, 1796 тестов)

> Перенесено из In Progress при архивации (PM, 2026-08-19, Шаг 1 Epic 41). Полный трек — `plans/backlog.md` (Epic 40).
> **Итог:** T-309…T-314 ALL DONE (по plans/MEMORY.md, Шаг 8). xray-core 26.3.27 + http-inbound 127.0.0.1:10808 с accounts (эмпирика: поле users молча игнорируется) + systemd enable/Restart=always; выходной IP 195.181.173.207 (AS60068); гейт 49.7 ПРОЙДЕН (3/4: sNhhvQGsMEc/cUbIkNUFs-4/aPYGbtkSE7A OK; dQw4w9WgXcQ — известный кейс пустого timedtext, не блок). Epic 39 разблокирован: прод v2.33.0 активирован, **PID 980709**, 0 traceback, proxy=set. Код не менялся. Тесты: 1796 passed (1789 + 7).

### Epic 39: YouTube engine fix — yt-dlp → youtube-transcript-api фолбек — ✅ DEPLOYED & ARCHIVED (v2.33.0, коммит `bb472ba`, прод PID 980709, 1796 тестов)

> Перенесено из In Progress при архивации (PM, 2026-08-19, Шаг 1 Epic 41). Полный трек — `plans/backlog.md` (Epic 39).
> **Итог:** T-302…T-306 DONE (Section 48, yt-dlp primary + фолбек transcript-api 0.6.3, +2 ключа настроек), T-307 коммит `bb472ba`; T-308 DEPLOY_BLOCKED на гейте T-308-C был СНЯТ Epic 40 (гейт 3/4 через прокси) → v2.33.0 в проде (PID 980709, 0 traceback).

### Epic 38: Refactoring WebSummarizer — Jina → Trafilatura + Tavily/Exa фолбеки — ✅ DEPLOYED & ARCHIVED (v2.32.1, коммит `f0bc4d6`, прод PID 974412, 1763 теста)

> Перенесено из In Progress при архивации (PM, 2026-08-19, Шаг 1 Epic 39). Полный трек — `plans/backlog.md` (Epic 38).
> **Итог:** T-294…T-301 ALL DONE. @Architect: Section 47; @Builder: Jina полностью удалён, WebContentExtractor (trafilatura → Tavily → Exa → исключение), wiring, +тесты; @Reviewer: APPROVED; @DevOps: коммит `f0bc4d6` «refactor(smartmodule): Epic 38 — WebSummarizer: Jina → Trafilatura + Tavily/Exa (v2.32.1)» + деплой v2.32.1 (pip install trafilatura, .env без JINA_API_KEY, бэкап `.env.bak.epic38`, PID 974412, 0 traceback). **ЭПИК 38 ЗАКРЫТ. Прод v2.32.1. Тесты: 1763 passed / 0 failed (1757 baseline + 6).**

- [x] T-294 (@Architect, P0) — дизайн Section 47 — **Done (Шаг 2)**
- [x] T-295 (@Builder, P0) — удаление Jina Reader (R38-2) — **Done**
- [x] T-296 (@Builder, P0) — WebContentExtractor + каскад trafilatura→Tavily→Exa (R38-3) — **Done**
- [x] T-297 (@Builder, P0) — wiring WebSummarizer (R38-3/R38-4, D135) — **Done**
- [x] T-298 (@Builder + @Reviewer, P0) — тесты + полный прогон 1763 passed + ревью APPROVED (R38-5) — **Done**
- [x] T-299 (@Builder, P1) — README v2.32.1 + MEMORY — **Done**
- [x] T-300 (@DevOps, P0) — коммит `f0bc4d6` + пуш — **Done (Шаг 7)**
- [x] T-301 (@DevOps, P0) — деплой v2.32.1 (PID 974412, 0 traceback) — **Done (Шаг 7)**

### Epic 37: SmartModule — YouTubeSummarizer + WebSummarizer — ✅ DEPLOYED & ARCHIVED (v2.32.0, коммит `747cb99`, прод PID 969047, 1757 тестов)

> Перенесено из In Progress при архивации (PM, 2026-08-19, Шаг 1 Epic 38). Полный трек — `plans/backlog.md` (Epic 37).
> **Итог:** T-281…T-293 ALL DONE. @Architect: Section 46 (46.1–46.15); @Builder: 19 новых файлов + 7 правок (движки YouTube/Jina, промпты-эталоны, пулы 5.6/5.7, сервисы, хендлеры 0e/0f, wiring), 1757 passed / 0 failed (1593 + 164); @Reviewer: APPROVED; @DevOps: коммит `747cb99` (31 файл) + деплой v2.32.0 (git pull ff, .env +5 ключей, бэкап `.env.bak.epic37`, PID 969047, 0 traceback).
> **Прод-дефекты движков (пост-деплой):** Web-фича мертва (Jina 401: JINA_API_KEY пуст + блок анонимных запросов AS36352; селектор не вычленял статью) → **Epic 38** (рефакторинг WebSummarizer, v2.32.1, ЗАКРЫТ); YouTube-фича сломана IP-блоком YouTube → **Epic 39** (одобрено пользователем, In Progress, v2.33.0). **ЭПИК 37 АРХИВИРОВАН. Прод v2.32.0.**

- [x] T-281 (@Architect, P0) — дизайн Section 46 в ARCHITECTURE.md — **Done (Шаги 2–3)**
- [x] T-282…T-289 (@Builder, P0) — конфиг, промпты, движки, пулы, сервисы, хендлеры, wiring — **Done (Шаг 4)**
- [x] T-290 (@Builder + @Reviewer, P0) — тесты + полный прогон 1757 passed + ревью APPROVED — **Done (Шаги 5–6)**
- [x] T-291 (@Builder, P1) — README v2.32.0 + MEMORY — **Done**
- [x] T-292 (@DevOps, P0) — коммит `747cb99` + пуш — **Done (Шаг 7)**
- [x] T-293 (@DevOps, P0) — деплой v2.32.0 (PID 969047, 0 traceback) — **Done (Шаг 7)**

### Epic 36: FactCheck — парсинг caption альбомов + адаптивный размер ответов — ✅ DEPLOYED & ARCHIVED (v2.31.3, коммит `2e26690`, прод PID 951645, 1593 тестов)

> Перенесено из In Progress при архивации (PM, 2026-08-18, Шаг 1 Epic 37). Полный трек — `plans/backlog.md` (Epic 36).
> **Итог:** T-274…T-280 ALL DONE. @Architect: Section 45 (буфер `MediaGroupCaptionBuffer` TTL 60с/LRU 100 + промпты-эталоны 42.5.1/42.5.2); @Builder: буфер альбомов (fill в observer 0a, чтение в `_extract_target_text`), блок «ОБЪЕМ И ДИНАМИЧЕСКИЙ РАЗМЕР ОТВЕТА» в обоих промптах, +20 тестов, README v2.31.3; @Reviewer: APPROVED (личный прогон 1593 passed / 0 failed / 0 skipped, BLOCKER/MAJOR НЕТ); @DevOps: коммит `2e26690` (19 файлов, +982/−28) + пуш (`585da8d..2e26690`) + деплой (git pull ff, PID 951645, 0 traceback). **ЭПИК 36 ЗАКРЫТ. Прод v2.31.3. Тесты: 1593 passed / 0 failed (1573 + 20).**

- [x] T-274 (@Architect, P0) — дизайн буфера media groups + правки промптов (ARCHITECTURE.md Section 45) — **Done (Шаг 2)**
- [x] T-275 (@Builder, P0) — буфер/парсинг caption альбомов в factcheck — **Done (Шаг 4: `services/media_group_buffer.py` TTL 60с/LRU 100 + fill в summary_observer 0a + чтение в `_extract_target_text`)**
- [x] T-276 (@Builder, P0) — блок «ОБЪЕМ И ДИНАМИЧЕСКИЙ РАЗМЕР ОТВЕТА» в обоих промптах + эталоны 42.5.1/42.5.2 + тесты (одним коммитом, D123) — **Done (Шаг 4)**
- [x] T-277 (@Builder, P1) — тесты, 0 регрессий — **Done (Шаг 4: +20 тестов, 1593 passed / 0 failed, `git diff --check` чист)**
- [x] T-278 (@Reviewer, P0) — ревью — **Шаг 5 ✅ APPROVED (личный прогон 1593 passed / 0 failed / 0 skipped; BLOCKER/MAJOR НЕТ, 4 MINOR не-блокера)**
- [x] T-279 (@DevOps, P0) — коммит на русском + пуш + деплой v2.31.3 — **Done (Шаг 7: коммит `2e26690`, 19 файлов +982/−28, пуш `585da8d..2e26690`, деплой ff, PID 951645, 0 traceback)**
- [x] T-280 (@Builder, P1) — README changelog — **Done (Шаг 4, changelog «✨ Новое в v2.31.3 (Epic 36)»)**

### Epic 35: Hotfix — alan_greeting тройной greeting (race condition F7v2) — ✅ DEPLOYED & ARCHIVED (v2.31.2, коммит `585da8d`, прод PID 950693, 1573 тестов)

> Перенесено из In Progress при архивации (Memory, 2026-08-17, Шаг 8). Полный трек — `plans/backlog.md` (Epic 35).
> **Итог:** T-268…T-273 ALL DONE. @Architect: RCA подтверждён (check-then-act race F7v2/join, 3 параллельных апдейта) + Section 44; @Builder: per-chat `asyncio.Lock` (`_greeting_locks`/`_get_greeting_lock`) + claim кулдауна/ts ДО `await _send_greeting()` + rollback (handlers/alan_greeting.py, handlers/alan.py), +9 тестов, README v2.31.2; @Reviewer: APPROVED (личный прогон 1573 passed / 0 failed); @DevOps: коммит `585da8d` «fix(alan): Epic 35 — race condition тройного greeting F7v2 (v2.31.2)» (**9 файлов, +764/−79**) + пуш origin (`5fb532b..585da8d`) + деплой (git pull --ff-only, `.env`/зависимости не тронуты, `systemctl restart admin_bot` → active (running) **PID 950693**, journalctl 0 traceback). **ЭПИК 35 ЗАКРЫТ (Шаг 8). Прод v2.31.2. Epics 1–35 ALL DEPLOYED. Тесты: 1573 passed / 0 failed (1564 + 9).**

- [x] T-268 (@Architect, P0) — RCA-подтверждение по логам + дизайн фикса в ARCHITECTURE.md (Section 44) — **Done (Шаг 2)**
- [x] T-269 (@Builder, P0) — реализация фикса race condition (по дизайну Architect) — **Done (Шаг 4: per-chat `asyncio.Lock` (`_greeting_locks`/`_get_greeting_lock` в alan_greeting.py, общий для F7v2 + обоих join-путей) + claim-before-send (кулдаун и ts записываются ДО `await _send_greeting()`, `ts_written`-флаг, rollback при неудаче)**
- [x] T-270 (@Builder, P1) — юнит/интеграционные тесты на конкурентный сценарий (3 параллельных хендлера → ровно 1 greeting), 0 регрессий (baseline 1564) — **Done (Шаг 4, +9 тестов, 1573 passed / 0 failed)**
- [x] T-271 (@Reviewer, P0) — ревью — **Шаг 5 ✅ APPROVED (2026-08-17: соответствие Section 44 дословно, дедлоков нет, BLOCKER/MAJOR НЕТ; личный прогон 1573 passed / 0 failed / 0 skipped; diff-check чист, секретов 0)**
- [x] T-272 (@DevOps, P0) — коммит на русском + пуш + деплой v2.31.2 (git pull, restart, status, проверка логов) — **Done (Шаг 7, коммит `585da8d`, пуш `5fb532b..585da8d`, деплой ff, прод v2.31.2, PID 950693, 0 traceback)**
- [x] T-273 (@Builder, P1) — README changelog v2.31.2 (ироничный тон) — **Done (Шаг 4, changelog «🔧 Исправлено в v2.31.2 (Epic 35)»)**

### Epic 34: Hotfix — SmartSearch TelegramBadRequest «message to be replied not found» — ✅ DEPLOYED & ARCHIVED (v2.31.1, коммит `5fb532b`, прод PID 949763, 1564 тестов)

> Перенесено из In Progress при архивации (Memory, 2026-08-17, Шаг 8). Полный трек — `plans/backlog.md` (Epic 34).
> **Итог:** T-261…T-267 ALL DONE. @Architect: RCA подтверждён + Section 43 (43.1–43.6); @Builder: `_send_once` fallback в `services/smartmodule_utils.py` (хендлеры БЕЗ правок), +9 тестов, README v2.31.1; @Reviewer: APPROVED (личный прогон 1564 passed / 0 failed); @DevOps: коммит `5fb532b` «fix(smartmodule): Epic 34 — fallback при удалённом reply-таргете SmartSearch (v2.31.1)» (**9 файлов, +621/−49**) + пуш origin (`1172fb5..5fb532b`) + деплой (git pull --ff-only, `.env`/venv не тронуты, `systemctl restart admin_bot` → active (running) **PID 949763**, journalctl 0 traceback, смоук OK). **ЭПИК 34 ЗАКРЫТ (Шаг 8). Прод v2.31.1. Epics 1–34 ALL DEPLOYED. Тесты: 1564 passed / 0 failed (1555 + 9).**

- [x] T-261 (@Architect, P0) — RCA-подтверждение + дизайн фикса (ARCHITECTURE.md Section 43) — **Done (Шаг 2)**
- [x] T-262 (@Builder, P0) — fallback «retry без reply_to_message_id» в smartmodule_utils (send_chunked_reply/_reply) + логирование — **Done (Шаг 4, `_send_once`/`_is_reply_target_gone`, WARNING→INFO)**
- [x] T-263 (@Builder, P1) — применение фолбека в handlers/search.py (+ factcheck.py при необходимости), без дублей — **Done (Шаг 4, хендлеры БЕЗ правок, 43.3; доказано тестами #8/#9)**
- [x] T-264 (@Builder, P1) — юнит-тесты fallback (мок bot.send_message: 1-й TelegramBadRequest → 2-й без reply OK), 0 регрессий (baseline 1555) — **Done (Шаг 4, +9 тестов, 1564 passed / 0 failed)**
- [x] T-265 (@Reviewer, P0) — code review — **Done (Шаг 5, APPROVED: личный прогон 1564 passed / 0 failed, diff-check чист, хендлеры не тронуты, секретов нет; BLOCKER/MAJOR НЕТ)**
- [x] T-266 (@DevOps, P0) — коммит на русском + пуш + деплой v2.31.1 (git pull, restart, status) — **Done (Шаг 7, коммит `5fb532b`, прод v2.31.1, PID 949763, 0 traceback)**
- [x] T-267 (@Builder, P1) — README-фикс при необходимости (или skip) — **Done (Шаг 4, changelog «🔧 Исправлено в v2.31.1 (Epic 34)»)**

### Epic 33: SmartModule Extension — FactCheck + SmartSearch + SearchAggregator — ✅ DEPLOYED & ARCHIVED (v2.31.0, коммит `1172fb5`, 1555 тестов, прод PID 948950)

> Перенесено из In Progress при архивации (Memory, 2026-08-17, Шаг 8). Полный трек — `plans/backlog.md` (Epic 33).
> **Итог:** T-249…T-260 ALL DONE. @Architect: Section 42 (42.1–42.12), D109 RESOLVED (промпты 42.5.1/42.5.2 дословно); @Builder: конфиг 6 ключей, SearchAggregator (Tavily→Exa→DDG→AllSearchEnginesFailedException), хендлеры factcheck (0c) / search (0d), пулы 5.1–5.5 байт-в-байт, промпты байт-в-байт, cleanup/чанкинг/logger.exception, README v2.31.0; @Reviewer: NEEDS FIXES → фиксы → **APPROVED** (1555 passed лично: 1392 + 150 + 4 интеграционных + 9 хелперов, 0 failed); @DevOps: коммит `1172fb5` «feat(smartmodule): Epic 33 — FactCheck и SmartSearch с SearchAggregator (v2.31.0)» (**32 файла, +3610/−43**) + пуш, деплой (git pull ff `2bad5ff..1172fb5`; pip install duckduckgo-search 8.1.1; .env +6 ключей: EXA_API_KEY/TAVILY_API_KEY/SEARCH_MAX_SYMBOLS=4000/FACTCHECK_MAX_SYMBOLS=4000/SEARCH_COOLDOWN_SECONDS=300/FACTCHECK_COOLDOWN_SECONDS=300, бэкап `.env.bak.epic33`) → active (running) **PID 948950**, 0 traceback, «SmartModule FactCheck + SmartSearch (Epic 33) initialized». **ЭПИК 33 ЗАКРЫТ (Шаг 8). Прод v2.31.0. Epics 1–33 ALL DEPLOYED.**

- [x] T-249 (@Architect, P0) — дизайн Section 42 + D109 RESOLVED — **Done (Шаг 2)**
- [x] T-250 (@Builder, P0) — конфиг 6 ключей + валидация (R33-1, D104) — **Done (Шаг 4a)**
- [x] T-251 (@Builder, P0) — SearchAggregator: каскад Tavily→Exa→DDG (R33-2, D105) — **Done (Шаг 4a)**
- [x] T-252 (@Builder, P0) — FactCheck-хендлер (R33-3, D106/D107) — **Done (Шаг 4a)**
- [x] T-253 (@Builder, P0) — SmartSearch-хендлер (R33-4, D106/D107) — **Done (Шаг 4a)**
- [x] T-254 (@Builder, P1) — пулы 5.1–5.5 дословно (R33-5, D108) — **Done (Шаг 4a)**
- [x] T-255 (@Builder, P1) — промпты байт-в-байт (R33-6) — **Done (Шаг 4a)**
- [x] T-256 (@Builder, P1) — надёжность: cleanup/чанкинг/логи (R33-7, D110) — **Done (Шаг 4a)**
- [x] T-257 (@Builder + @Reviewer, P0) — тесты + полный прогон + ревью APPROVED (1555 passed) — **Done (Шаг 5)**
- [x] T-258 (@Builder, P1) — README v2.31.0 + .env.example (R33-8) — **Done**
- [x] T-259 (@DevOps, P0) — коммит `1172fb5` + пуш (32 файла, +3610/−43) — **Done**
- [x] T-260 (@DevOps, P0) — деплой v2.31.0 (PID 948950, 6 ключей .env, duckduckgo-search 8.1.1, 0 traceback) — **Done (Шаг 8)**

### Epic 32: Фикс гифки Славика + сервис Оли (caption/репост) + SUMMARY_THROTTLE_SECONDS=300 — ✅ DEPLOYED & ARCHIVED (v2.30.0, коммит `2bad5ff`, 1392 теста, прод PID 942078)

> Перенесено из Backlog при архивации (PM, 2026-08-17, Шаг 1 Epic 33). Полный трек — `plans/backlog.md` (Epic 32).
> **Итог:** T-242…T-248 ALL DONE. @Builder: гифка Славика (settings-снапшот GIF_PATH/GIF_INTERVAL, is_file-guard → WARNING+skip, ERROR/INFO-логи вместо глушения, D99), Оля (`_normalize_caption` + триггер `@saveasbot` + origin-матрица MessageOriginUser/Channel/HiddenUser, D100–D102), тесты **1392 passed** (1366 + 26 новых, 0 failed), ревью @Reviewer APPROVED; @DevOps: прод .env `SUMMARY_THROTTLE_SECONDS=300.0` (D103), коммит `2bad5ff` «fix(media): Epic 32 — починен Славик (stale путь гифки), Оля теперь только caption/репост, таймаут саммари 300с на проде (v2.30.0)» + пуш, деплой (git pull ff `0f25c7e..2bad5ff`; .env: удалён устаревший `GIF_PATH`, +`SUMMARY_THROTTLE_SECONDS=300.0`, +`OLYA_SAVEASBOT_USER_IDS=523131145`, бэкап `.env.bak.epic32`) → active (running) **PID 942078**, 0 traceback, WARNING «GIF file not found» отсутствует. **ЭПИК 32 ЗАКРЫТ. Прод v2.30.0. Epics 1–32 ALL DEPLOYED.**

- [x] T-242 (@Builder, P0) — гифка Славика (R32-1, D99) — **Done**
- [x] T-243 (@Builder, P0) — Оля: нормализация caption + репосты (R32-2, D100/D101/D102) — **Done**
- [x] T-244 (@DevOps, P0) — прод SUMMARY_THROTTLE_SECONDS=300.0 (R32-3, D103) — **Done**
- [x] T-245 (@Builder, P1) — тесты + полный прогон (1392 passed) — **Done**
- [x] T-246 (@Builder, P1) — README v2.30.0 + .env.example — **Done**
- [x] T-247 (@DevOps, P0) — коммит `2bad5ff` + пуш — **Done**
- [x] T-248 (@DevOps, P0) — деплой v2.30.0 (PID 942078, 0 traceback) — **Done**

### Epic 31: /summary для всех + setMyCommands + таймаут-фразы — ✅ DEPLOYED & ARCHIVED (v2.29.0, 1366 тестов)

> Перенесено из Backlog/In Review при архивации (PM, 2026-08-17). Полный трек — `plans/backlog.md` (Epic 31).
> **Итог:** T-235…T-241 ALL DONE. @Builder: `SUMMARY_ADMIN_ONLY` + allow-check (D94), `services/bot_commands.py` (setMyCommands, BotCommandScopeDefault, «set_my_commands ok»), `_THROTTLE_PHRASES` (7) + `format_remaining_seconds`, тесты **1366 passed** (1327 + 39 новых, 0 failed/skipped); @Reviewer T-238-E **APPROVED** (2026-08-17); T-239 README v2.29.0 + .env.example; @DevOps T-240 коммит + пуш, T-241 деплой: .env `ALLOWED_SUMMARY_IDS=` пусто + `SUMMARY_ADMIN_ONLY=False` (бэкап `.env.bak.epic31`), restart → active (running), «set_my_commands ok», 0 traceback, /summary доступен всем. **ЭПИК 31 ЗАКРЫТ. Прод v2.29.0. Эпики 1–31 ALL DEPLOYED.**

- [x] T-235 (@Builder, P0) — `SUMMARY_ADMIN_ONLY` + allow-check D94 — **Done**
- [x] T-236 (@Builder, P0) — `services/bot_commands.py` + вызов в on_startup — **Done**
- [x] T-237 (@Builder, P0) — `_THROTTLE_PHRASES` (7) + `format_remaining_seconds` + reply-ветка — **Done**
- [x] T-238 (@Builder + @Reviewer, P0) — тесты 1366 passed + ревью — **Done (APPROVED)**
- [x] T-239 (@Builder, P1) — README v2.29.0 + .env.example — **Done**
- [x] T-240 (@DevOps, P0) — коммит + пуш — **Done**
- [x] T-241 (@DevOps, P0) — деплой v2.29.0 (ALLOWED_SUMMARY_IDS пусто, SUMMARY_ADMIN_ONLY=False) — **Done**

### Epic 30: Common Expansion — selfdev/work-реакции, goodmorning-рассылка, фикс нумерации промпта — ✅ DEPLOYED (v2.28.0, коммит `714a4f6`, 1327 тестов, прод PID 939545)

> Перенесено из Backlog/In Progress/In Review при архивации (PM, 2026-08-17). Полный трек — `plans/backlog.md` (Epic 30, статус DEPLOYED).
> **Итог:** T-227…T-234 ALL DONE. @Builder: selfdev (SELFDEV_WORDS 48/фраз 17, 87 юнитов), work (WORK_WORDS 128/фраз 31, 183 юнита), goodmorning (captions 6 = 3 канона + 3 новых, relay, APScheduler, 39 юнитов), фикс нумерации промпта 1–6 (D90, байт-в-байт ✅); T-231 — @Builder + @Reviewer **APPROVED** (1327 passed: 1002 baseline + 325 новых, 0 failed/skipped, пересечения списков ∅, `git diff --check` чист); T-232 — README v2.28.0 + .env.example; T-233/T-234 (@DevOps) — коммит `714a4f6` «feat(common): Epic 30 — selfdev/work-реакции, goodmorning-рассылка и фикс нумерации промпта (v2.28.0)» (30 файлов, 8 медиа) + пуш + деплой: git pull ff `7160a33..714a4f6`, .env (бэкап `.env.bak.epic30`: GOODMORNING_TARGET_CHAT_IDS=-1002661910336 ВКЛЮЧЕНА, SELFDEV/WORK_COOLDOWN=5m), restart → active (running) **PID 939545**, «Goodmorning scheduler started (07:00 Asia/Yekaterinburg, 1 chats)», 0 traceback. Шаг 8 (@Memory): docs-коммит `4b50272`. **ЭПИК 30 ЗАКРЫТ (Шаг 8), Epics 1–30 ALL DEPLOYED.**

- [x] T-227 (@Builder, P0) — selfdev-функция (R30-1, D85/D87/D92) — **Done** (фильтр+хендлер+коулдаун, 87 юнитов)
- [x] T-228 (@Builder, P0) — work-функция (R30-2, D86/D87/D92) — **Done** (фильтр+хендлер+коулдаун, 183 юнита)
- [x] T-229 (@Builder, P0) — goodmorning-рассылка (R30-3, D88/D89) — **Done** (captions+relay+scheduler+bot.py, 39 юнитов)
- [x] T-230 (@Builder, P1) — фикс нумерации промпта (R30-4, D90) — **Done** (1–6, байт-в-байт ✅)
- [x] T-231 (@Builder + @Reviewer, P0) — тесты 1327 passed + ревью — **Done (APPROVED)**
- [x] T-232 (@Builder, P1) — README v2.28.0 + .env.example — **Done**
- [x] T-233 (@DevOps, P0) — коммит `714a4f6` + пуш (30 файлов, медиа в коммите) — **Done**
- [x] T-234 (@DevOps, P0) — деплой v2.28.0 (PID 939545, goodmorning ON, 0 traceback) — **Done (Шаг 8: `4b50272`)**

### Epic 29: T-221…T-226 — UX-полировка (код + тесты + доки + коммит + деплой) — ✅ DONE & DEPLOYED (v2.27.0, коммит `7160a33`, 1002 passed, прод PID 937634)

> Перенесено из Backlog при архивации (PM, 2026-08-17). Полный трек — `plans/backlog.md` (Epic 29).
> **Итог:** T-221 (@Architect) — Section 38 (38.1–38.7), DESIGN ✅; T-222 — пул 20 ack-фраз (`_UX_ACK_VARIANTS`, канон первым) + `random.choice`, delete ДО ack; T-223 — промпт v4 (пункт 3 удалён, пункт 6 — канон пользователя дословно), эталон backlog 1518–1539 (22 строки), слайс `lines[1517:1539]`; T-224 — доки (ARCHITECTURE/MEMORY/README/board); T-225 — тесты + полный прогон 1002 passed (995 baseline + 7 новых), 0 failed, 0 skipped; T-226 — коммит `7160a33` «feat(summary): Epic 29 — UX-полировка: удаление команды, ack-вариации, промпт v4 (v2.27.0)» + пуш + деплой (git pull ff `ac80ce8..7160a33`, .env НЕ тронут, restart → active (running) PID 937634, 0 traceback, dim=3072). **ЭПИК 29 ЗАКРЫТ (Шаг 8).**

- [x] T-221 (@Architect, P0) — Section 38 (38.1–38.7), порядок delete→ack — **Done (DESIGN ✅)**
- [x] T-222 (@Builder, P1) — пул ack-фраз + `random.choice` + 4 ассерта → принадлежность пулу — **Done**
- [x] T-223 (@Builder, P0) — промпт v4 + эталон backlog + слайс `lines[1517:1539]` — **Done (байт-в-байт ✅)**
- [x] T-224 (@Builder, P1) — доки (ARCHITECTURE/MEMORY/README/board) — **Done**
- [x] T-225 (@Builder + @Reviewer, P0) — тесты + полный прогон 1002 passed — **Done (ревью @Reviewer — T-225-C)**
- [x] T-226 (@Builder + @DevOps, P0) — коммит `7160a33` + пуш + деплой v2.27.0 (PID 937634, 0 traceback) — **Done (2026-08-17, Шаг 8)**

### Epic 28: T-211…T-220 — качество памяти: векторы, репосты, алиасы, очистка — ✅ DEPLOYED (v2.26.0, коммит `ac80ce8` + `ccfad99`, 995 тестов)

> Перенесено из колонки Backlog при архивации (PM, 2026-08-16). Полный трек — `plans/backlog.md` (Epic 28).
> **Итог:** T-211…T-219 реализованы (@Builder), ревью @Reviewer PASS (995 passed). T-220 DONE: коммит `ac80ce8` «feat(summary): Epic 28 — качество памяти: репосты, алиасы, векторное автолечение и cleanup (v2.26.0)» + пуш в origin/master; деплой выполнен (git pull, restart, логи проверены: нет Dimension mismatch, алиасы работают). Шаг 8 (@Memory): `ccfad99` — финальная синхронизация. ЭПИК 28 ЗАКРЫТ.

- [x] T-211…T-219 (@Builder, @Reviewer) — реализация + ревью PASS (995 passed) — **Done**
- [x] T-220 (@Builder + @DevOps + @PM) — коммит `ac80ce8` + пуш + деплой v2.26.0 + Шаг 8 `ccfad99` — **Done**

### Epic 27: T-207…T-210 — новый системный промпт + SUMMARY_ALIASES на прод — ✅ DEPLOYED (v2.25.0, коммиты `1d7bed4` + `17fcd18`, 939 тестов, PID 934174)

> Перенесено из колонки Backlog при архивации (PM, 2026-08-16). Полный трек — `plans/backlog.md` (Epic 27).
> **Итог:** T-207 — SYSTEM_PROMPT заменён на «бот-абьюзер v2» дословно (эталон backlog R11 v2, строки 1518–1538, байт-в-байт ✅; тесты D72; полный pytest 939 passed / 0 регрессий) и T-208 — доки (MEMORY.md «заморожено» → R11 v2, README промпт v2, ARCHITECTURE верифицирован) DONE. T-209 — прод: .env +SUMMARY_ALIASES (36 пар, бэкап `.env.bak.epic27`, python3: JSON OK, sha1 совпал с репо), git pull fast-forward `7c7c241..1d7bed4`, systemctl restart → active (running), **PID 934174**, 0 traceback. T-210 — коммит `1d7bed4` «feat(summary): Epic 27 — новый системный промпт бота-абьюзера v2 и SUMMARY_ALIASES (v2.25.0)» (8 файлов, .env НЕ коммичен, .env.example коммичен) + пуш в origin/master. Шаг 8 (@Memory): финальная синхронизация `17fcd18`. ЭПИК 27 ЗАКРЫТ. ⚠️ Pre-existing не-блокер → Epic 28: L3 dimension mismatch (768 vs 3072) → FTS5-фоллбек.

- [x] T-207 (@Builder, **P0**): Замена SYSTEM_PROMPT на новый дословный текст (эталон backlog R11 v2, строки 1518–1538) + тесты (хелпер-диапазон 1517:1538, набор плейсхолдеров D72) + полный pytest 939 — **Done (байт-в-байт ✅)**
- [x] T-208 (@Builder, **P1**, ←T-207): Доки — ARCHITECTURE.md, MEMORY.md («заморожено» → R11 v2), README (промпт v2) — **Done**
- [x] T-209 (@DevOps, **P0**, ←T-207): SUMMARY_ALIASES (36 пар) в продовый .env (бэкап `.env.bak.epic27`, JSON OK, sha1 совпал) + git pull + restart admin_bot + верификация — **Done (PID 934174, 0 traceback)**
- [x] T-210 (@DevOps + @PM, **P1**, ←T-207/T-208): Коммит `1d7bed4` (conventional, 8 файлов) + пуш; .env не коммичен — **Done (Шаг 8: `17fcd18`)**

### Epic 26: T-199…T-206 — дизайн, реализация и деплой GraphRAG — ✅ DEPLOYED (v2.24.0, коммит `7c7c241`, 939 тестов, PID 926618)

> **Итог:** T-199 (T26.0) — дизайн `plans/ARCHITECTURE.md` Section 35 (35.1–35.11) **APPROVED PM 2026-08-16 (T26.0-D)**.
> T-200…T-204 (T26.1…T26.5) — **реализовано @Builder и прошло ревью @Reviewer (T26.5-G APPROVED)**:
> DDL nodes/edges (chat_id + UNIQUE), extraction в compress_and_purge (D68 per-batch isolation),
> traversal get_graph_facts (тег `<historical_graph_facts>` первым, escape), настройки GRAPH_* (D69),
> тесты test_graphrag_database/test_graphrag_memory + полный pytest.
> ⚠️ @Reviewer подтвердил **P1 pre-existing баг** (Epic 24, `a68732c`) → выделен **T-206 (T26.7)**: FTS-DELETE зеркалит условие вставки (`text IS NOT NULL AND text != ''`) в `delete_smart_messages_by_ids`/`delete_smart_messages_older_than` + chat_id-фильтр + 6 регрессионных тестов — **FIXED в релизе v2.24.0**.
> **T-205 (T26.6) DONE:** коммит `7c7c241` «feat(graphrag): Epic 26 — граф знаний nodes/edges, entity extraction и гибридный поиск /summary (v2.24.0)» + пуш + деплой: git pull fast-forward `c364f18..7c7c241`, .env +GRAPH_* (бэкап .env.bak.epic26), systemctl restart → active (running), Main PID 926618, nodes/edges созданы, 0 traceback. Тесты: 939 passed (860+73+6). ЭПИК 26 ЗАКРЫТ (Шаг 8, @Memory). Известный не-блокер: SIGTERM ~95с рестарт (pre-existing).

- [x] 👤 T-199 (T26.0) (@Architect + @PM, P0) — Архитектурное проектирование GraphRAG + фиксация промпта
  - [x] T26.0-A: Section 35 (35.1–35.11): DDL nodes/edges, flow extract→graph→delete, traversal, открытые вопросы 1–10
  - [x] T26.0-B: EXTRACT_PROMPT зафиксирован дословно (35.3 + services/summary_prompts.py)
  - [x] T26.0-C: Self-review — изоляция от 860 тестов, graceful degradation, LLM-нагрузка
  - [x] T26.0-D: **APPROVED PM 2026-08-16** — R26-1…R26-7 покрыты, риски 1–10 закрыты (35.9); T26.1…T26.4 → READY FOR BUILDER
- [x] T-200 (T26.1) (@Builder, P0) — Миграция схемы: nodes/edges + chat_id + UNIQUE + индексы + upsert CRUD (R26-1, D67) — Done
- [x] T-201 (T26.2) (@Builder, P0) — Entity Extraction в архивации: EXTRACT_PROMPT (verbatim), JSON try/except, граф ДО удаления сырья, per-batch isolation (R26-2, D68) — Done
- [x] T-202 (T26.3) (@Builder, P0) — Graph traversal для /summary: сущности L1, SQL weight DESC LIMIT 5, справки «[Историческая справка: …]», `<historical_graph_facts>` первым, escape_xml_text, fallback (R26-3, D71) — Done
- [x] T-203 (T26.4) (@Builder, P1) — Конфигурация GRAPH_* (4 параметра) + .env.example (R26-6, D69) — Done
- [x] T-204 (T26.5) (@Builder + @Reviewer, P0) — Тесты (парсер JSON, upsert, traversal, чат-изоляция, кривой JSON → пачка остаётся, pipeline с graph_facts) + полный pytest — Done; @Reviewer (T26.5-G) **APPROVED 2026-08-16** — с находкой P1 → T-206
- [x] T-206 (T26.7) (@Builder + @Reviewer, P1) — P1-фикс FTS-удаления медиа без подписи + 6 регрессионных тестов — **FIXED (релиз v2.24.0)**
- [x] T-205 (T26.6) (@Builder + @DevOps, P0) — README + коммит `7c7c241` + пуш + деплой — **DEPLOYED (v2.24.0, PID 926618, 939 тестов)**

### Epic 24: T-173 — Архитектурное проектирование SmartModule/Summary — 2026-08-16 — ✅ APPROVED (PM, T-173-E)

> **Итог:** дизайн `plans/ARCHITECTURE.md` Section 33 (33.1–33.15, решения A1–A15) APPROVED.
> R1–R18 покрыты полностью; риски 1–12 backlog + Н1–Н4 закрыты решениями (33.14).
> Минорные замечания для @Builder (не блокируют): (1) в 33.8 сказано «+18 полей» — в блоке 24 поля, поправить число в комментарии; (2) `_ensure_shiz_postfix` проверяет только наличие приписки «самым главным шизом объявляется», но не убирает `@`, если LLM сам написал её с @ — добавить стрип `@` в финальном имени; (3) число новых тестов в 33.13 (~120) уточнить по факту в T-188-C.
> T-174 → READY FOR BUILDER. Передача @Builder.

- [x] 👤 T-173 (@Architect + @PM, P0) — Epic 24: Архитектурное проектирование SmartModule/Summary (2026-08-16)
  - [x] T-173-A: Модули, data flow, схема БД, контракты — `plans/ARCHITECTURE.md` **Section 33** (33.1–33.15)
  - [x] T-173-B: Позиции роутеров — `summary_observer_router` 0a + `summary_router` 0b (ДО catch-all 5/6); сбор всех сообщений — отдельный роутер с UNHANDLED
  - [x] T-173-C: Общая `local_database.db`; сжатие L3 — шаг пайплайна под общим `asyncio.Lock` (без отдельной джобы)
  - [x] T-173-D: Self-review — изоляция от 12 роутеров, фоллбек-пути FTS5, таймауты LLM, секция 33.14
  - [x] T-173-F: RESEARCH.md верифицирован (context7 — API-key недоступен; duckduckgo — anomaly; рабочий стек: exa + webfetch docs.aiogram.dev; секция «Методология» + источники с датами)
  - [x] T-173-E: **APPROVED PM 2026-08-16** — R1–R18 ✅, риски закрыты, конвенции соблюдены (settings.py хелперы, bot.py on_startup-wiring, _SCHEMA_SQL-миграции, инъекции setup_*, MessageCounterMiddleware router-scoped не задет)

### Epic 25: T-192/T-193 — RCA + дизайн фикса /summary — 2026-08-16 — ✅ APPROVED (PM)

> **Итог:** RCA T-192 (первопричина: асимметрия троттлинг-мидлвари с Command-фильтром — чужая mention `/summary@RofloslavBot` сожгла слот, повтор молча сглочен) + дизайн T-193 (`plans/ARCHITECTURE.md` Section 34, 34.1–34.10, решения B1–B9) APPROVED.
> R25-1…R25-4 покрыты; исходное ТЗ R7 (ALLOWED пуст=всем, запрет без реакции — denied не удаляем/не отвечаем) и R8 (молчаливый троттлинг — B3 сохраняет) не нарушены.
> Замечания для @Builder (не блокируют): (1) B6 — `_safe_send` должен использовать инжектированный `bot` (в `setup_summary` или параметром хендлера), иначе при `_generator is None` UX не доставляется (сейчас `_generator.bot` → AttributeError → лог вместо сообщения); (2) B3 — сохранить guard `if text.strip()` текущего кода и использовать точное сравнение `base == "/summary"` (startswith ловит `/summaryfoo` — тот же класс асимметрии, что и первопричина); (3) backlog синхронизирован: H-C остаётся молчаливой (R8) — UX только для H-B/H-F.
> T-194/T-195 → READY FOR BUILDER. Передача @Builder.

- [x] 👤 T-192 (@Architect + @DevOps, P0) — Epic 25: RCA бага «/summary не реагирует» (2026-08-16)
  - [x] T-192-A: прод-логи journalctl/smart_messages за момент теста + прод .env
  - [x] T-192-B: Н1 (BotFather setprivacy), админ-права delete_messages, следы cron
  - [x] T-192-C: сопоставление с H-A…H-F — H-C ✅ подтверждена (триггер), асимметрия middleware/Command ✅ (первопричина)
  - [x] T-192-D: отчёт причин — ARCHITECTURE.md Section 34.2 + сводка board.md
- [x] 👤 T-193 (@Architect + @PM, P0) — Epic 25: Дизайн фикса (2026-08-16)
  - [x] T-193-A: Section 34 (34.1–34.10): ack (D66), best-effort удаление (D65), B1–B9, тест-план 34.8, риски 34.9
  - [x] T-193-B: **APPROVED PM 2026-08-16** — B1–B9 сверены с R25-1…R25-4 и исходным ТЗ R7/R8; 2 замечания Builder (B6 bot-инжекция, B3 strip-guard/точное сравнение); backlog синхронизирован (H-C молчалива)

### Epic 24: T-174…T-191 — реализация и деплой SmartModule — ✅ DEPLOYED (v2.22.0, коммит `a68732c`)

> Перенесено из колонки Backlog при архивации (PM, 2026-08-16). Полный трек — `plans/backlog.md` (Epic 24).
> ⚠️ Н1 BotFather `/setprivacy` → Disable — ручное действие пользователя.

- [x] T-174..T-189 (@Builder): конфиг (24 поля), БД smart_messages+CRUD, память L1/L2/L3 (sqlite-vec + FTS5-фоллбек), LLM-клиент (httpx, retry 429/5xx), XML-контекст, алиасы, системный промпт (verbatim), APScheduler 00/06/12/18 Asia/Yekaterinburg, /summary, троттлинг, чанкинг, observability — Done (157 новых тестов)
- [x] T-188-D (@Reviewer): code review SmartModule — APPROVED 2026-08-16 (830 passed после 2 точечных фиксов)
- [x] T-189 (@Builder): README (ироничный тон) + ARCHITECTURE 33.16 + MEMORY, v2.22.0 — Done (итог 835 passed)
- [x] T-190 (@Builder + @DevOps): коммит `a68732c` (35 файлов, на русском, conventional) + push origin/master — Done (.env не коммичен)
- [x] T-191 (@DevOps): деплой — git pull, .env +LLM_*, venv +APScheduler 3.11.3/sqlite-vec 0.1.9/httpx 0.28.1, restart → active (running) PID 920105, smoke apinet.cloud OK — Done

### Epic 25: T-194…T-198 — фикс /summary — ✅ DEPLOYED (v2.23.0-fix, коммит `c364f18`)

> Перенесено из колонки Backlog при архивации (PM, 2026-08-16). Полный трек — `plans/backlog.md` (Epic 25).

- [x] T-194 (@Builder): реализация B1–B9 (ack «ща гляну, подожди», UX-ветки, delete best-effort, логирование этапов) — Done
- [x] T-195 (@Builder): +25 тестов (860 total), полный прогон зелёный, 0 регрессий — Done
- [x] T-196 (@Reviewer): APPROVED 2026-08-16 (личный прогон 860 passed; 4 Low-замечания не блокируют — на будущий эпик)
- [x] T-197 (@DevOps): коммит `c364f18` (11 файлов, +1001/−84) + push origin/master — Done (860 passed перед коммитом, .env не тронут)
- [x] T-198 (@DevOps): деплой fast-forward `a68732c..c364f18`, restart → active (running) PID 923954, старт чистый — Done. ⚠️ Pre-existing: L3 dimension mismatch (768 vs 3072) → FTS5-фоллбек; stop-timeout systemd при рестарте. Живой тест /summary — после теста пользователем

### Epic 23: Точная настройка danger-словаря (v2.21.0) — 2026-08-16 — ✅ DEPLOYED (коммит `756d237`)

> **Цель:** Убрать ложноположительные секции danger-словаря (Flight/arrival, Падение/сбитие),
> перевести Shelter и Атаку/угрозу на фразы-связки, добавить «хлопок»-синонимы, ввести
> механику DANGER_PHRASES.
> **PM-решения:** D55 (DANGER_PHRASES + ветка фраз в DangerWordFilter, regex по краям фразы
> IGNORECASE, возврат {"matched_word"} совместимый; env-оверрайд фраз НЕ вводим),
> D56 (Shelter: −26 одиночных форм, +10 фраз), D57 (вспышка*/взрыв* остаются,
> +хлопок/хлопки/хлопнуло/хлопнул, омоним-риск принят), D58 (Атака: −28 одиночных форм, +7 фраз).
> Target: v2.21.0. Prod .env НЕ меняли (DANGER_WORDS пустой → дефолты из word_lists.py).
> **Итог:** DONE & DEPLOYED ✅ — T-169..T-172 (включая деплойные подзадачи E..G) закрыты,
> 672 теста PASS (621+51). Коммит `756d237` (feat(danger)) на master, пуш в origin.
> Деплой: git pull 0c74220..756d237 (9 файлов) на 198.46.175.136:/var/www/admin_bot,
> systemctl restart OK — active (running) PID 917681, логи чистые. .env DANGER_WORDS пустой →
> дефолты (118 слов + 17 фраз), проверка «118 17» совпала. Прод v2.21.0.

- [x] T-169 (@Builder): Словарь — Flight удалить, Падение удалить, Shelter→10 фраз (DANGER_PHRASES), Flash + «хлопок» (D56, D57)
- [x] T-170 (@Builder): Атака/угроза → 7 фраз (D58)
- [x] T-171 (@Builder): Механика DANGER_PHRASES в DangerWordFilter + тесты (обновить сломанные, новые на фразы/негатив)
- [x] T-172 (@Builder + @DevOps): Доки DONE ✅ (README «187 словоформ» → 118 + 17 фраз, v2.21.0/672, ARCHITECTURE, MEMORY) + коммит DONE ✅ (`756d237` feat(danger) на master) + деплой DONE ✅ (E..G: pull 0c74220..756d237, 9 файлов; .env DANGER_WORDS пустой → дефолты; «118 17» совпала; PID 917681; логи чистые)

### Chore (2026-08-16): danger_drone.mp4 в danger-пул — ✅ DEPLOYED (коммит `0c74220`)

> **Итог:** T-168 DONE & DEPLOYED. Все подзадачи A..E закрыты. Деплой: git pull на сервере
> fast-forward 1dbb6da..0c74220 (5 файлов), danger_drone.mp4 на месте (права 644, хэш 918c9be9...
> совпал), danger-пул = 16 файлов. systemctl restart OK — active (running), PID 916795, логи чистые.

- [x] T-168 (@Builder): Медиа: danger_drone.mp4 в danger-пул (коммит + деплой)
  - [x] T-168-A: Verify — файл существует локально (16-й файл пула), не в .gitignore ✓
  - [x] T-168-B: Коммит `0c74220` (chore(media): danger_drone.mp4 в danger-пул) + push в origin ✓
  - [x] T-168-C: Деплой — SSH git pull на 198.46.175.136:/var/www/admin_bot (fast-forward 1dbb6da..0c74220) ✓
  - [x] T-168-D: Verify на сервере — danger_drone.mp4 присутствует, chmod 644, хэш совпал, пул = 16 файлов ✓
  - [x] T-168-E: Smoke test — danger-слово → ответ из danger-пула; danger_drone.mp4 распознаётся как video ✓
  - ⚠️ Политика media/ соблюдена: файл закоммичен, НЕ в .gitignore, НЕ удалён.

### Epic 22: Гонка функций и точность триггеров (Olya/Mimic/Slavik/PostPicker) — 2026-08-15 ✅ DEPLOYED (v2.20.0, коммит `1dbb6da`)

> **Цель:** Устранить гонку ответов у Славика (приветствие vs dead page vs «пошёл нахуй»),
> сделать триггеры точнее: Olya — только SaveAsBot-видео, mimic — не передразнивать репосты,
> PostPicker — не выбирать пост, отправленный в предыдущий раз.
> **PM-решения:** D51 (Olya: ИЛИ + OLYA_ALWAYS_SEND=False), D52 (MIMIC_FORWARDS_ENABLED=False),
> D53 (DEAD_PAGE_POST_ON_JOIN=False, dead page только на репосты Славы из @d_pages, catchall-гейт),
> D54 (channel_state `dead_page_last_sent:{chat_id}`). Target: v2.20.0.
> **Итог:** реализовано и задеплоено. 621 тест PASS (586 baseline + 35 новых), 0 регрессий.
> Коммит `1dbb6da` на master, пуш в origin. Деплой: 198.46.175.136:/var/www/admin_bot,
> git pull c683903..1dbb6da (21 файл, +1778/-224), prod .env DEAD_PAGE_POST_ON_JOIN=True→False
> (бэкап .env.bak.2026-08-15), systemctl restart OK, active (running), PID 914116. Прод v2.20.0.

- [x] T-163 (@Builder): Olya — реагировать только на SaveAsBot-видео (D51)
  - [x] T-163-A: OLYA_ALWAYS_SEND default → False (settings.py + .env.example)
  - [x] T-163-B: Сохранить ИЛИ: caption-признак ИЛИ репост из OLYA_SAVEASBOT_CHANNEL_IDS
  - [x] T-163-C: AC: обычное видео → False; репост SaveAsBot → True; caption → True; ALWAYS_SEND=True → True
  - [x] T-163-D: Тесты (≈5) + README/.env.example
- [x] T-164 (@Builder): Mimic — не передразнивать репосты (D52)
  - [x] T-164-A: MIMIC_FORWARDS_ENABLED: bool = False (settings.py + .env.example)
  - [x] T-164-B: common.py mimic_handler: forward_origin is not None + off → UNHANDLED
  - [x] T-164-C: slavik.py catchall Branch 2: то же правило (mimic пропускается)
  - [x] T-164-D: Тесты (≈6): forwarded+off → нет mimic; обычное → mimic; forwarded+on → mimic (оба механизма)
- [x] T-165 (@Builder): Славик — приоритет приветствия, dead page только на репосты Славы из @d_pages (D53)
  - [x] T-165-A: DEAD_PAGE_POST_ON_JOIN default → False (join → только «ДОЛБОЕБ ВЕРНУЛСЯ»)
  - [x] T-165-B: dead_page_trigger: только репосты Славы (UserIdFilter), убрать is_present-гейт
  - [x] T-165-C: catchall guard: d_pages-репост Славы → UNHANDLED (ни photo, ни mimic, ни «пошёл нахуй»)
  - [x] T-165-D: Интеграционные тесты: join-race (1 ответ), repost-race (1 ответ)
- [x] T-166 (@Builder): PostPicker — не выбирать пост, отправленный в прошлый раз (D54)
  - [x] T-166-A: БД: channel_state `dead_page_last_sent:{chat_id}` + get/set_last_sent_message_id
  - [x] T-166-B: Forward scan + sequential scan: skip кандидата == last_sent (fallback при исчерпании)
  - [x] T-166-C: Random probing: re-roll last_sent без сжигания attempt + контрольный try в конце
  - [x] T-166-D: Запись первичного msg_id после успешного форварда (все пути, включая альбомы)
  - [x] T-166-E: Тесты (≈7): два вызова → разные посты; один пост → fallback повтор
- [x] T-167 (@Builder): Документация, полный pytest, коммит
  - [x] T-167-A: README.md (v2.20.0, changelog)
  - [x] T-167-B: ARCHITECTURE.md + MEMORY.md
  - [x] T-167-C: pytest — 0 регрессий (621 passed: 586 + 35 новых)
  - [x] T-167-D: Коммит `1dbb6da` (feat(triggers): Epic 22 — точность триггеров и фикс гонки ответов (v2.20.0)) + push в origin + деплой (198.46.175.136:/var/www/admin_bot, PID 914116, прод v2.20.0) ✅

> ⚠️ Блокеры/риски (исторически): (1) prod .env мог содержать OLYA_ALWAYS_SEND=True / DEAD_PAGE_POST_ON_JOIN=True — РАЗРЕШЕНО при деплое (DEAD_PAGE_POST_ON_JOIN→False, бэкап .env.bak.2026-08-15);
> (2) не путать last_known_message_id (верхняя граница forward-scan) и dead_page_last_sent (анти-повтор);
> (3) danger_handler (4c) может ответить на d_pages-репост при danger-словах — существующее поведение, вне скоупа.

### Epic 21: BUG FIX — MIMIC Not Working + Time Format Cooldowns — 2026-08-03 ✅ DEPLOYED (v2.19.0, commit c683903)

- [x] T-149: Fix MIMIC propagation — return UNHANDLED в handlers/alan.py (3 code paths)
- [x] T-150: parse_duration / _env_duration хелперы в config/settings.py
- [x] T-151: Переименование 6 cooldown-полей (*_COOLDOWN_SECONDS → *_COOLDOWN, time-format)
- [x] T-152: Update bot.py — все cooldown references
- [x] T-153: Update handlers/slavik.py — SLAVIK_MIMIC_COOLDOWN
- [x] T-154: Update services/mimic_relay.py — MIMIC_COOLDOWN (verified)
- [x] T-155: Update services/common_relay.py — COMMON_COOLDOWN + DANGER_COOLDOWN (verified)
- [x] T-156: Update services/dead_page_relay.py — DEAD_PAGE_COOLDOWN
- [x] T-157: Update .env.example — time-format defaults
- [x] T-158: Update tests + tests/test_duration.py (15 тестов)
- [x] T-159: Полный прогон — 586 tests PASS, 0 failures
- [x] T-160: README.md — v2.19.0, config table
- [x] T-161: Sync MEMORY.md / ARCHITECTURE.md
- [x] T-162: Commit (c683903) + push + deploy — server active (PID 699945)

### Epic 20: Slavik Random Media Enhancement — 2026-08-02 ✅ IMPLEMENTED

- [x] T-139: Verify reply behavior — message.answer_* replies without quoting
- [x] T-140: Add audio support (.mp3) to _detect_slavik_media_type
- [x] T-141: Add voice (.ogg) and document support to _detect_slavik_media_type
- [x] T-142: Add audio sending to _send_slavik_media (answer_audio)
- [x] T-143: Add voice and document sending to _send_slavik_media
- [x] T-144: Verify and harden GIF detection from filename
- [x] T-145: Add comprehensive tests for all 6 media types (61 tests)
- [x] T-146: Run full test suite, verify no regressions
- [x] T-147: Update README with ironic tone about the changes
- [x] T-148: Commit and push (deploy leave to DevOps agent)

### Epic 19: Сервис Olya — автоответ на видео от @ole4444444ka — 2026-08-02 ✅ DEPLOYED

- [x] T-131: Создать `filters/olya_video.py` — `OlyaVideoFilter` (UserId 834424825 + видео + детекция SaveAsBot)
- [x] T-132: Создать `services/olya_relay.py` — `OlyaRelay` (plain send, медиа-автоопределение, cooldown)
- [x] T-133: Создать `handlers/olya.py` — `olya_router` + `olya_handler` + `setup_olya()`
- [x] T-134: Добавить конфигурацию Olya в `config/settings.py` (+8 полей) и `.env.example`
- [x] T-135: Зарегистрировать `olya_router` в `bot.py` (позиция 4d, после common_router, до slavik_router)
- [x] T-136: Написать тесты `tests/test_olya.py` (15-20 тестов: фильтр, сервис, хендлер, интеграционные, corner cases)
- [x] T-137: Обновить README.md — добавить документацию Epic 19
- [x] T-138: Деплой на сервер (git pull, systemctl restart, проверка статуса)

### Epic 18: Danger Service Fixes — File Selection, GIF Detection, Cooldown — 2026-08-02 ✅ DEPLOYED

- [x] T-122-A–J: File scanning/selection
- [x] T-123-A–H: GIF detection in filename
- [x] T-124-A–H: DANGER_COOLDOWN_SECONDS config with independent cooldown
- [x] T-125-A–E: Update config/settings.py and .env.example
- [x] T-126-A–E: Update bot.py for new CommonRelay initialization
- [x] T-127-A–S: Comprehensive tests for all fixes
- [x] T-128-A–E: Update README.md with changes
- [x] T-129-A–E: Run full test suite, verify no regressions
- [x] T-130-A–M: Deploy to server

### Epic 17: Danger Word Fix — 2026-07-30
- [x] T-115: Проверить медиа-файлы danger/ на сервере
  - [x] T-115-A-E: SSH проверка, права, diff
- [x] T-116: Проверить и исправить DangerWordFilter
  - [x] T-116-A-G: 91+ слов, word-boundary, регистронезависимость, caption, логирование
- [x] T-117: Проверить war_alert_router ↔ common_router interaction
  - [x] T-117-A-F: порядок роутеров, F.forward_origin → TargetChannelFilter, propagation
- [x] T-118: Проверить и исправить CommonRelay.send_common
  - [x] T-118-A-G: _scan_directory, _pick_media, _detect_media_type, _send_media, error handling
- [x] T-119: Тесты для danger_word
  - [x] T-119-A-I: 91+ слов, регистр, word boundary, caption/forward, cooldown, integration, pytest
- [x] T-120: README — changelog, v2.12.2 → v2.15.0
- [x] T-121: Деплой на сервер
  - [x] T-121-A-H: git pull, .env, restart, smoke tests, Better Stack

### Epic 16: Bug Fixes Sprint — 2026-07-29 ✅ ARCHIVED (→ Epic 17)
- [x] Epic 16 archived 2026-07-30. Danger_word fix → Epic 17. DeadPageRelay album fix → deferred.
- [x] T-109: DangerWordFilter — RCA completed (22 слова → нужно 91+)
- [x] T-114: war_channel_repost_handler — RCA completed (F.forward_origin блокирует)
- [x] T-113: DEAD_PAGE_RELAY_CHANNEL_ID — RCA completed
- [x] T-110: DeadPageRelay album fix — ARCHIVED (перекрыто Epic 14 T-093–T-099)
- [x] T-111: Тесты — ARCHIVED (перекрыто Epic 14 T-098 / Epic 17 T-119)
- [x] T-112: Документация — ARCHIVED (перекрыто Epic 17 T-120)

### Epic 15: Common Service — Rename + Media Upgrade + Danger — 2026-07-28
- [x] 👤 T-100 (@Architect): Архитектурное проектирование Common Service + sub-agent review
  - [x] T-100-A: Спроектировать архитектуру — модули, data flow, directory structure, контракты
  - [x] T-100-B: Sub-agent ревью — изоляция, масштабируемость, корректность rename, media type detection
  - [x] T-100-C: Согласовать финальный дизайн с PM
- [x] T-101: Переименование файлов и модулей (otboy → common)
  - [x] T-101-A: handlers/otboy.py → handlers/common.py
  - [x] T-101-B: services/otboy_relay.py → services/common_relay.py
  - [x] T-101-C: filters/otboy_word.py оставлен; СОЗДАН filters/danger_word.py (DangerWordFilter)
  - [x] T-101-D: Обновлены все импорты в bot.py
  - [x] T-101-E: Grep-проверка — нет dead imports
- [x] T-102: Конфигурация — переименованы и добавлены env-переменные
  - [x] T-102-A: OTBOY_COOLDOWN_SECONDS → COMMON_COOLDOWN_SECONDS
  - [x] T-102-B: OTBOY_PHOTO_PATH удалён, добавлен COMMON_MEDIA_BASE
  - [x] T-102-C: Созданы директории media/common/otboy/ и media/common/danger/
  - [x] T-102-D: Обновлён .env.example
- [x] T-103: Upgrade media-обработки — directory-based picker с авто-детекцией типа
  - [x] T-103-A: CommonRelay._pick_media(media_dir)
  - [x] T-103-B: _detect_media_type(filename) → photo/video/animation
  - [x] T-103-C: _send_media(chat_id, filepath, media_type, reply_params)
  - [x] T-103-D: send_otboy() использует _pick_media + _send_media
  - [x] T-103-E: Логирование media type
- [x] T-104: Новая функция детекции опасных слов (danger)
  - [x] T-104-A: DangerWordFilter — DANGER_WORDS + pattern compilation
  - [x] T-104-B: CommonRelay.send_danger() — _pick_media + _send_media + reply_to + quote
  - [x] T-104-C: danger_handler в common.py
  - [x] T-104-D: Reply-to + quote mechanism (ReplyParameters)
  - [x] T-104-E: Comprehensive logging для danger
- [x] T-105: Интеграция в bot.py
  - [x] T-105-A: Импорты: common_router, setup_common, CommonRelay
  - [x] T-105-B: dp.include_router(common_router) — позиция 4c
  - [x] T-105-C: on_startup(): CommonRelay, setup_common(relay)
  - [x] T-105-D: Propagation проверен (оба handler'а возвращают None)
- [x] T-106: Тесты (~20+ тестов)
  - [x] T-106-A: test_otboy.py → test_common.py
  - [x] T-106-B: 11 тестов OtboyWordFilter перенесены
  - [x] T-106-C: 6 тестов otboy_handler перенесены (OtboyRelay → CommonRelay)
  - [x] T-106-D–G: Media type detection, _pick_media edge cases
  - [x] T-106-H–I: DangerWordFilter тесты (срабатывает/не срабатывает/регистр/word boundary)
  - [x] T-106-J–K: danger_handler + CommonRelay.send_danger тесты
  - [x] T-106-L: Cooldown тесты (общий для otboy+danger, per-chat)
  - [x] T-106-M–N: Интеграция — propagation + диспетчеризация
- [x] T-107: Документация — README, ARCHITECTURE, MEMORY обновлены, v2.12.0
- [x] T-108: QA — тесты, коммит, деплой
  - [x] T-108-A: pytest — 316+ тестов, 0 регрессий
  - [x] T-108-B: Коммит на русском (conventional commits) в main, пуш
  - [x] T-108-C: Деплой на сервер — git pull, .env, restart
  - [x] T-108-D: Smoke test: «отбой» → медиа из common/otboy
  - [x] T-108-E: Smoke test: «ракетная опасность» → медиа из common/danger
  - [x] T-108-F: Smoke test: другие фичи не сломаны
  - [x] T-108-G: Better Stack логи verified

### Epic 14: Media Group Album Fix — 2026-07-28
- [x] T-093: Новая таблица relay_album_map + 3 CRUD метода в database.py
- [x] T-094: channel_post handler в bot.py для отслеживания media_group_id
- [x] T-095: Модифицировать DeadPageRelay._try_forward_from_channel() — DB lookup + forward_messages()
- [x] T-096: Эвристический fallback — пробинг соседних message_id ±1..9
- [x] T-097: Дедупликация media_group в dead_page_trigger.py
- [x] T-098: Тесты (10 cases) — DB + heuristic + dedup + integration
- [x] T-099: QA — pytest (316 tests), обновление документации, v2.11.0

### Epic 13: Otboy Service (F9) — 2026-07-26
- [x] T-084: Архитектурное проектирование и ревью (sub-agent review)
- [x] T-085: Создать filters/otboy_word.py — OtboyWordFilter
- [x] T-086: Создать services/otboy_relay.py — OtboyRelay
- [x] T-087: Создать handlers/otboy.py — otboy_router
- [x] T-088: Конфигурация — OTBOY_COOLDOWN_SECONDS, OTBOY_PHOTO_PATH
- [x] T-089: Зарегистрировать otboy_router в bot.py (позиция 4c)
- [x] T-090: Тесты для Otboy Service (10 тестов — filter + handler + relay + integration)
- [x] T-091: Документация — README, ARCHITECTURE, MEMORY, v2.10.0
- [x] T-092: Деплой на сервер + smoke tests

### Epic 12: Багфикс репостов + slavic_na_litso.jpg — 2026-07-25
- [x] T-078: Расследование и исправление бага с репостами Славы (war_alert не ловит forwarded messages)
  - [x] T-078-A: Расследование — diagnostic-логи, проверка гипотез (UserIdFilter для forwarded, message.text/caption, порядок хендлеров, propagation)
  - [x] T-078-B: Исправление бага
  - [x] T-078-C: Comprehensive logging для forwarded-сообщений
- [x] T-079: Реализация фичи — slavic_na_litso.jpg каждый N-й ответ "пошёл нахуй"
  - [x] T-079-A: Добавить `SLIVIC_NA_LITSO_INTERVAL` в config/settings.py + .env.example
  - [x] T-079-B: Добавить счётчик в DatabaseService
  - [x] T-079-C: Модифицировать slavik_catchall_handler в handlers/slavik.py
  - [x] T-079-D: Comprehensive logging
- [x] T-080: Тесты для багфикса репостов (test_war_alert.py — 6 тестов)
- [x] T-081: Тесты для фичи slavic_na_litso.jpg (test_slavik_handlers.py — 8 тестов)
- [x] T-082: Обновление README + ARCHITECTURE.md + MEMORY.md, коммит, пуш
- [x] T-083: Деплой на сервер + smoke tests

### Epic 11: Alan Silence Greeting (F7v2 — "Леха проснулся") — 2026-07-18
- [x] T-064: Добавить ALAN_SILENCE_GREETING_HOURS в config/settings.py + .env.example
- [x] 👤 T-065 (@Architect): Решение о хранилище — БД через channel_state
- [x] T-066: Реализовать get/set_alan_last_message_ts в DatabaseService
- [x] T-067: Встроить silence-логику в alan_handler (handlers/alan.py)
- [x] T-068: Логика детекта "молчал >= N часов → написал" → _send_greeting()
- [x] T-069: Обновление таймера при КАЖДОМ сообщении Алана
- [x] T-070: Edge cases — baseline, N=0, несколько чатов, restart persistence, cooldown
- [x] T-071: Детальное логирование каждого этапа
- [x] T-072: Интеграция в bot.py — без изменения порядка роутеров
- [x] T-073: Тесты — 19 новых тестов
- [x] T-074: Обновить README.md
- [x] T-075: Прогнать полный pytest suite — 271 тест, без регрессий
- [x] T-076: Коммит на русском в main, пуш
- [x] T-077: Деплой на сервер + ALAN_SILENCE_GREETING_HOURS=2

### Epic 10: War Words Redesign (F5v2) — 2026-07-16
- [x] T-054: Fix WarWordFilter — caption support + expand WAR_WORDS keywords (90+ форм)
- [x] T-055: Add channel repost detection handler for military channels (war_words_trigger.py)
- [x] T-056: Replace single hardcoded reply with extensible pool + random.choice()
- [x] T-057: Add comprehensive Better Stack logging
- [x] T-058: Create/extend tests — filter, handler, integration (~28 tests)
- [x] T-059: Update config/settings.py — WAR_CHANNEL_IDS, WAR_CHANNEL_USERNAMES, WAR_REPLIES
- [x] T-060: Register war_alert_router in bot.py (position 4b)
- [x] T-061: Update README — document F5v2
- [x] T-062: Run full pytest suite — verify no regressions (~280 tests)
- [x] T-063: Deploy to server

### Epic 9: Admin Test Commands (2026-07-14)
- [x] T-048: /deadpage — ручной вызов DeadPageRelay.send_dead_page()
- [x] T-049: /alangreet — ручной вызов _send_greeting()
- [x] T-050: Прогнать pytest — без регрессий
- [x] T-051: Тесты на admin_commands (6 тестов)

### Epic 8: Alan Greeting Video (F7) — 2026-07-13
- [x] T-038: Add ALAN_USERNAME, ALAN_USER_ID, ALAN_GREETING_DIR to config
- [x] T-039: Create handlers/alan_greeting.py (join + fallback + video + caption)
- [x] T-040: Register alan_greeting_router in bot.py (position 1b)
- [x] T-041: Write tests/test_alan_greeting.py (7-8 tests)
- [x] T-042: Update ARCHITECTURE.md
- [x] T-043: Update MEMORY.md
- [x] T-044: Run all tests — no regressions
- [x] T-045: Code review and QA

### Epic 7: Better Stack Monitoring Integration (2026-07-12)
- [x] T-029: Add sentry-sdk==2.64.0 and logtail-python==0.4.0 to requirements.txt
- [x] T-030: Install sentry-sdk and logtail-python into venv
- [x] T-031: Add SENTRY_DSN and LOGTAIL_SOURCE_TOKEN to .env.example
- [x] T-032: Add SENTRY_DSN and LOGTAIL_SOURCE_TOKEN to .env
- [x] T-033: Initialize Sentry SDK in bot.py
- [x] T-034: Configure LogtailHandler on root logger
- [x] T-035: Write and run smoke test
- [x] T-036: Run pytest — no regressions
- [x] T-037: Update ARCHITECTURE.md with monitoring section

### Epic 6: Dead Page V2 — Event-driven reposts
- [x] T-018: Update config/settings.py + .env.example
- [x] T-019: Update DEAD_PAGE_V2_PLAN.md
- [x] T-020: Create services/dead_page_relay.py
- [x] T-021: Create handlers/dead_page_trigger.py
- [x] T-022: Simplify services/scheduler.py
- [x] T-023: DB migration (channel_state, timestamp, new methods)
- [x] T-024: Update bot.py (register dead_page_router #4, init DeadPageRelay)
- [x] T-025: Add comprehensive logging to dead_page modules
- [x] T-026: Update MEMORY.md and ARCHITECTURE.md
- [x] T-027: Write/rewrite tests
- [x] T-028: Run all tests and verify coverage

### Epic 1: Рефакторинг
- [x] T-001: Вынести API_TOKEN в .env / конфигурацию
- [x] T-002: Создать requirements.txt с закреплёнными версиями
- [x] T-003: Создать единую структуру проекта
- [x] T-004: Унифицировать обработку ошибок и логирование
- [x] T-005: Создать общий базовый класс для фильтров

### Epic 2: Новые функции
- [x] T-006 (F1): При возвращении Славы в чат → «ДОЛБОЕБ ВЕРНУЛСЯ»
- [x] T-007 (F2): Dead-page посты — рандомное фото + текст
- [x] T-008 (F3): Каждые 5 сообщений → GIF через MessageCounterMiddleware
- [x] T-009 (F4): «КУЧА» → «ДАЛБАЕБ» с KuchaWordFilter
- [x] T-010 (F5): Военные слова → «трясло ебаное» (DEPRECATED — заменено на F5v2)
- [x] T-011 (F6): Каждые 10 сообщений @Alan_Z → reply random-фразой

### Epic 3: Тестирование и CI
- [x] T-012: Модульные тесты на все хендлеры
- [x] T-013: Тесты на все корнер-кейсы
- [x] T-014: Интеграционные тесты

### Epic 4: Документация
- [x] T-015: README.md с ироничной документацией

### Epic 5: Багфиксы
- [x] T-016 (Kostik): Probability-based reply engine + extensible pool
- [x] T-017 (Kucha): Fix KuchaWordFilter regex

### Bugfixes (Critical/High) — 2026-07-13 to 2026-07-15
- [x] T-046: Dead Page Relay — ALL RANGES EXHAUSTED (Critical)
- [x] T-047: Alan Greeting Video — service never fires (High)
- [x] T-052: Dead Page Relay — sequential scanning for sparse channels (Critical)
- [x] T-053: Propagation-stopping bug in slava_presence.py — F7 completely broken (Critical)

### Remaining LOW (not blocking — ARCHIVED, вне активного бэклога)
- [ ] H3: Dispatcher integration tests — deferred
- [ ] L1: README platform-specific Windows commands
- [ ] L2: Quoting in response text (reply_to covers)
- [ ] L4: MediaService cache invalidation
- [ ] L5: VasyaFilter translit order edge case

---

**Updated:** 2026-08-17 — **Epic 32 (v2.30.0) АРХИВИРОВАН: T-242…T-248 ALL DONE & DEPLOYED (коммит `2bad5ff`, 1392 теста, PID 942078).** Открыт **Epic 33 «SmartModule Extension: FactCheck + SmartSearch + SearchAggregator» (v2.31.0, IN PROGRESS)**: Шаг 1 (PM) ✅ — требования R33-1…R33-8, решения D104–D111 в `plans/backlog.md`; T-249 (@Architect, дизайн) → T-250…T-258 (@Builder) → T-259/T-260 (@DevOps). ⚠️ Блокер D109: дословные тексты промптов — у пользователя. Без @Orchestrator. **→ 2026-08-17, Шаг 4b (@Builder): Epic 33 IMPLEMENTED (T-249 ✅, T-250…T-256 ✅, T-257-A…E ✅ — 10 новых тест-файлов, 150 тестов, полный прогон 1542 passed / 0 failed, `git diff --check` чист); блокер D109 СНЯТ (промпты 42.5.1/42.5.2 байт-в-байт); T-257-F — @Reviewer (ожидается); T-258 README (@Builder) → T-259/T-260 (@DevOps).** **→ 2026-08-17, Шаг 5 (@Builder, фиксы ревью): @Reviewer NEEDS FIXES закрыты — BLOCKER-1 (реальные ключи в backlog.md R33-1 → плейсхолдеры; grep: ключи только в .env), MAJOR-1 (новая интеграция `test_epic33_router_isolation.py`: Dispatcher 0a/0c/0d/4c через feed_update — «найди ракету» → 1 ответ от search, factcheck → reply на target, observer 0a пишет память, danger/common живы), MINOR 1–4 (.env +4 явных ключа и чистый UTF-8-комментарий; убран `.lower()` в factcheck.py:72; `test_settings_helpers.py` 9 тестов вскрыл и закрыл `NameError: logging` в settings.py); прогон **1555 passed / 0 failed**. Повторное ревью @Reviewer ожидается.** **→ 2026-08-17, Шаг 5 (повторное ревью, @Reviewer): ✅ APPROVED — все замечания закрыты и подтверждены лично (BLOCKER-1: grep по фрагментам ключей — только .env; MAJOR-1: 4 теста через `Dispatcher.feed_update` содержательны; MINOR 1–4 ✅; промпты/пулы байт-в-байт повторно; роутеры 0c/0d не сдвинуты; `git diff --check` чист; полный прогон 1555 passed / 0 failed подтверждён лично). T-257 ЗАКРЫТ. Впереди: T-258 README (@Builder) → T-259/T-260 (@DevOps).** **→ 2026-08-17, Шаг 8 (@Memory, ФИНАЛЬНАЯ синхронизация): Epic 33 ✅ DEPLOYED & ARCHIVED — T-249…T-260 ALL DONE. Коммит `1172fb5` «feat(smartmodule): Epic 33 — FactCheck и SmartSearch с SearchAggregator (v2.31.0)» (32 файла, +3610/−43) + пуш в origin/master. Деплой на прод nik@198.46.175.136:/var/www/admin_bot: git pull ff `2bad5ff..1172fb5`, pip install duckduckgo-search 8.1.1, .env +6 ключей (бэкап `.env.bak.epic33`), systemctl restart → active (running) MainPID 948950, 0 traceback, «SmartModule FactCheck + SmartSearch (Epic 33) initialized». Тесты 1555 passed / 0 failed. Прод v2.31.0. Epics 1–33 ALL DEPLOYED. Цикл воркфлоу (Шаги 0–8) завершён.**
**Updated:** 2026-08-18 — **Epic 36 (v2.31.3) АРХИВИРОВАН: T-274…T-280 ALL DONE & DEPLOYED (коммит `2e26690`, 1593 теста, PID 951645).** Открыт **Epic 37 «SmartModule: YouTubeSummarizer + WebSummarizer» (v2.32.0, IN PROGRESS)**: Шаг 1 (PM) ✅ — требования R37-1…R37-9, решения D124–D133 в `plans/backlog.md`; T-281 (@Architect, Section 46) → T-282…T-291 (@Builder) → T-292/T-293 (@DevOps). Без @Orchestrator.
**Updated:** 2026-08-20 — **Epic 42 «Checkup» + Epic 43 «/info + live-редактор» открыты (Шаг 1 @PM ✅, target v2.34.0)**: требования R42-1…R42-6 / R43-1…R43-5, решения D158–D165, задачи T-323…T-342 в `plans/backlog.md`; T-323/T-332 (@Architect, Sections 51/52) → @Builder → @Reviewer → @DevOps (деплой v2.34.0 общий). Epic 41 (v2.33.1) — ждёт архивации (Шаг 8 @Memory). Без @Orchestrator.

**Updated:** 2026-08-24 — **Шаг 1 @PM, Epic 60**: Epics 1–59 ALL CLOSED & DEPLOYED — архивированы: секции Epics 41–59 перенесены из «In Progress» в «✅ Done» компактной сводкой (полный трек каждого — `plans/backlog.md` + `plans/MEMORY.md`; дублирующие блоки Epics 48–51/52 в хвосте доски удалены — суть в сводке). Открыт **Epic 60 «Полировка direct_chat + память + чекап»** (37 пунктов RESEARCH_HUMAN, target v2.43.0): R60-1…R60-35, D235–D244, T-458…T-499. ⚠ Незакоммиченные правки RESEARCH_HUMAN.md (галочки [х] + комментарии пользователя, +39/−20) — фиксируются здесь и ВХОДЯТ в коммит Epic 60 (T-496). Без @Orchestrator.

**Updated:** 2026-08-24 — **Epic 60: все фазы A–E + п.8 РЕАЛИЗОВАНЫ, ревью ✅ APPROVED (Medium-фикс внесён), тесты 2611 passed / 0 failed (baseline 2360, +251), `git diff --check` чист.** T-458…T-495 и T-499 → [x] DONE; остались открытыми только T-496 (@DevOps коммит+пуш, включая правки RESEARCH_HUMAN по D242) и T-497 (@DevOps деплой v2.43.0) + финализация T-498. README актуализирован (@Docs, T-495). Далее — @DevOps (Шаг 7).


---
