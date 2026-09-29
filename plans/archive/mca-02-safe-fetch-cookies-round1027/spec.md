# `mca-02-safe-fetch-cookies` — спецификация (Step 2 @Architect, T-3799)

- **Эпик:** Раунд 10.27 `memory-context-autonomy` (MCA), **Wave 1** (данные). **Фича-ID:** `mca-02-safe-fetch-cookies`.
- **Тип:** backend/security — общий SafeFetcher (SSRF/redirect/egress/лимиты/видео-профиль/ошибки/маскирование) + аудит cookies/профиля. **Независима** от схемы identity (DDL не требуется); может вестись параллельно с `mca-03`.
- **Источник (IMMUTABLE, R17/R18):** `plans/current_task.md` v1.8 **§6** (`:141–178`): §6.1 (`:153–162`), §6.2 (`:170–178`); §2.15 (`:35`), §2.16/§17.3 (`:36`,`:838–846`), §3 (`:45–47`), §4 (`:99`), §19 **A22/A23** (`:903`,`:904`), §21.7 (`:1056`), §22 (`:1073–1074`).
- **Задачи:** `tasks.md` T-3798…T-3815. **Приёмки:** A22, A23.
- **ADR:** `adr-1027-5-safe-fetch-cookies.md` (D1–D12). **Рамка:** `plans/docs/mca-round1027-arch-frames.md`.
- **Статус:** Proposed → Accepted по T-3814 (Merge §97+). **Deploy:** `DEFERRED_TO_RELEASE`.
- **Risk-Level:** **R3** — безопасность внешних загрузок (SSRF/rebinding/декомпрессионные бомбы) и сохранность авторизации видеосервисов; ошибка может открыть внутреннюю сеть либо разлогинить/сломать production video-pipeline. Обязателен `threat-failure-analysis.md` (Блок H). Триггеры понижения до R2: подтверждённая блокировка private/internal для всех путей, эквивалентный egress-контроль для подпроцессов, зелёные A22/A23 на фактическом diff.
- **Baseline (Step 0, данность):** HEAD `7165ff7`; `APP_VERSION` 2.58.31; SQLite DDL **v15**; каталог `473/430/448/102/100/21`; канон 12; pytest 9588/0 + JS 47/47; reviewed-commit `05bc870`.
- **Зависимости:** нет обязательных предшественников. Совместно: `mca-13` ✅ (события §17.1/§17.2 — REUSE), `mca-14` ✅ (если DDL — через реестр; ожидается Δ DDL=0), `mca-01` ✅ (сеть/LLM вне транзакции записи). Потребители/смежные: `mca-11` (ToolResult/`fetch_article`), `mca-19` (vision bytes/MIME/декомпрессия), `mca-release` (отчёт cookies §21.7).

## 1. Область и исключения

**Входит:** общий SafeFetcher для URL из чата и инструментов (схемы HTTP/HTTPS, нормализация, запрет встроенных credentials; проверка IPv4/IPv6/localhost/private/link-local/reserved/metadata; проверка **каждого** redirect и **фактически используемого адреса подключения** (anti-rebinding); эквивалентный контроль назначения/egress для медиа-подпроцессов/yt-dlp/прокси/обходящих клиентов; отдельная конфигурация доверенных API/локальных служб; потоковые лимиты переданных **и распакованных** байтов, timeout, параллелизм; отдельный видео-профиль загрузки на диск; ошибки со кодом/стадией/причиной; маскирование секретов); аудит cookies/профиля, исключение секретов из упаковки без удаления на сервере, политика переноса/cleanup, проверка авторизованного video-сценария; события MCA-13/стадии MCA-17a; R17.

**Не входит (границы):**
- **ToolResult/`fetch_article`-конверт, лимиты цепочек, media async** — `mca-11`; MCA-02 отдаёт fetch-примитив, `mca-11` оборачивает результат.
- **Vision/MediaAsset: bytes/MIME/analysis, decompression-bomb для изображений в контексте vision** — `mca-19` (потребляет SafeFetcher-контракт; MCA-02 владеет сетевым fetch/SSRF/лимитами).
- **Download-контракт** — REUSE ADR-1016-1 (не переписывать).
- **Отчёт cookies §21.7 в итоговом релизе** — ведёт `mca-release`; MCA-02 готовит R17-safe вход.
- **Новая инфраструктура/микросервисы** — запрещены (§4); egress-контроль — loopback/in-process.
- **Изменение поведения скачивания в baseline** — только под kill-switch (OFF = паритет).

### 1.1. Фактическое состояние baseline (сверено с рабочей веткой; REUSE §3)

- `services/web_content_extractor.py`: `httpx.AsyncClient`, `follow_redirects=True`, `timeout` 10/15 c, **без** SSRF-проверок; каскад trafilatura → Tavily → Exa. **Дефект §6.1 присутствует.**
- `services/image_generation.py::_download_bytes` (`:825–847`) читает `response.content` целиком, затем проверяет `len(content) > max_bytes` — ровно анти-паттерн §6.1 («после полной загрузки недостаточно»). **Дефект присутствует.**
- `services/youtube_transcript_engine.py`/`tools/video_downloader.py`: yt-dlp (`YoutubeDL`) с `proxy`/`cookiefile`, transcript-api с resident-proxy, Cobalt (`COBALT_API_URL` default `http://localhost:9000`); dest-контроля/egress-guard нет. **Дефект §6.1 присутствует.**
- `services/llm_probe.py::_safe_base` (`:166–188`) — **существующий** минимальный SSRF-паттерн (https; http только для точного loopback-хоста) — **REUSE паттерна** (хост через `urlsplit`, не `startswith`).
- Cookies/профиль: `config/settings.py::YOUTUBE_COOKIES_FILE` (`:1179`), `build_ytdlp_base_opts` → `cookiefile` (`:2007–2009`), `YOUTUBE_TRANSCRIPT_PROXY_URL/USERNAME/PASSWORD/DOMAIN/PORT`, hot `keys.youtube_cookies_file`/`keys.youtube_transcript_proxy_*`; `handlers/youtube.py:268`; `tools/cookies_export.py` (`--profile` user_data_dir, `--out` Netscape, yt-dlp subprocess); `tools/video_downloader.py::download_env_summary` (presence-only, R17-safe). **Аудит потребителей — не завершён; упаковка/перенос/cleanup — не формализованы.**
- `services/media_download.py` — Telegram `getFile`/`bot.download` (внутренний транспорт, не пользовательский URL) — вне SafeFetcher, но фиксируется как граница.

## 2. Трассируемость REQ → SC

| REQ | §ТЗ | SC | Задачи |
|---|---|---|---|
| REQ-MCA02-01 — SafeFetcher: HTTP/HTTPS, нормализация, запрет встроенных credentials | §6.1 `:155` | SC-01 | T-3802 |
| REQ-MCA02-02 — проверка IPv4/IPv6/localhost/private/link-local/reserved/metadata; каждый redirect и фактический адрес подключения (anti-rebinding) | §6.1 `:156–157` | SC-02, SC-03 | T-3803 |
| REQ-MCA02-03 — эквивалентный egress/назначение для медиа-подпроцессов/yt-dlp/прокси/обходящих клиентов | §6.1 `:158` | SC-04 | T-3804, T-3806 |
| REQ-MCA02-04 — отдельная конфигурация доверенных API/локальных служб (не сломать глобальным запретом) | §6.1 `:159` | SC-05 | T-3803, T-3812 |
| REQ-MCA02-05 — потоковые лимиты переданных и распакованных байтов, timeout, параллелизм | §6.1 `:160` | SC-06 | T-3804, T-3810 |
| REQ-MCA02-06 — отдельный профиль загрузки видео на диск, совместимый с текущими размерами; HTML-лимит к видео не применять | §6.1 `:161` | SC-07 | T-3804 |
| REQ-MCA02-07 — ошибки: код/стадия/причина; маскирование секретов | §6.1 `:162` | SC-08 | T-3805 |
| REQ-MCA02-08 — аудит потребителей cookies/профиля/mounts/скриптов; исключение из упаковки без удаления на сервере | §6.2 `:172–173`; §2.15 | SC-09, SC-10 | T-3807, T-3808 |
| REQ-MCA02-09 — перенос в закрытый runtime-каталог с правами; проверка авторизованного video-сценария; cleanup только после подтверждения (`cleanup_deferred_dependency_unverified`); сессии не отзывать; секреты не в отчёт | §6.2 `:174–178`; §21.7 | SC-11, SC-12 | T-3808, T-3809, T-3813 |
| REQ-MCA02-10 — producers/consumers/e2e; сеть вне транзакции записи | §4 `:99`; §6.1 | SC-13 | T-3806, T-3810 |
| REQ-MCA02-11 — Δ DDL 0 / Δ каталога 0; kill-switch; deploy `DEFERRED_TO_RELEASE`; события MCA-13/R17 | §18; §17.1–§17.3; §20 | SC-14, SC-15 | T-3800, T-3811, T-3812, T-3813 |

**Орфан-REQ нет;** T-3798/3801/3814/3815 — процессные (PM/сверка/ревью-merge/архив).

## 3. Наблюдаемое поведение и отказы

- Обычная ссылка открывается; опасное назначение (loopback/private/link-local/reserved/metadata, IPv4 и IPv6) или слишком большая загрузка останавливается с понятной причиной; сервер сохраняет работоспособность.
- Redirect проверяется на **каждом** шаге; фактически используемый адрес подключения проверяется (rebinding не обходит защиту).
- Большой stream блокируется **без полного чтения в RAM** (переданные и распакованные байты лимитированы потоково).
- Крупное видео скачивается на диск отдельным профилем; HTML-лимит к нему не применяется.
- Ошибка несёт код, стадию и понятную причину; секретные query/cookies/proxy credentials замаскированы.
- Обычные ссылки и видео продолжают обрабатываться; доверенные API/локальные службы не сломаны.
- Cookies/профиль не удаляются, если это нарушает скачивание/транскрибацию/субтитры/выжимку; исключение из упаковки не удаляет файл на сервере.
- OFF kill-switch = точный legacy-путь (baseline parity).

## 4. Интерфейсы и контракты

### 4.1. Общий SafeFetcher (D1)
- Единый модуль `services/safe_fetch.py`; `services/web_content_extractor.py` **AMEND** → использует SafeFetcher (не второй fetcher). Потребители: web-извлечение, `youtube_transcript_engine`, скачивания, `fetch_article` (`mca-11`), image-download (`mca-19`).
- **Нормализация (D2):** схема только `http`/`https`; host → lowercase/IDN(→punycode); удаление default-порта и dot-сегментов; **запрет userinfo/встроенных credentials**; запрет control-символов/backslash; отклонение `file:`/`gopher:`/`ftp:`/`data:` и пр.
- **SSRF-проверки (D3):** resolve A/AAAA; блокировать loopback (`127/8`,`::1`), private (`10/8`,`172.16/12`,`192.168/16`), link-local (`169.254/16`,`fe80::/10`), CGNAT (`100.64/10`), ULA (`fc00::/7`), multicast/unspecified/ reserved/broadcast, IPv4-mapped IPv6 (`::ffff:0:0/96`), и metadata-эндпоинты (`169.254.169.254`, `fd00:ec2::254`, `100.100.100.200`, `metadata.google.internal`).
- **Anti-rebinding (D3):** `follow_redirects=False` + ручной цикл redirect (≤5), каждая новая цель нормализуется и проверяется заново; после подключения фактический peer-адрес проверяется через `response.extensions["network_stream"].get_extra_info("server_addr")` (httpx ≥0.21/httpcore; сверено с установленным httpx 0.28.1). Несовпадение с валидированным набором → блок (`destination_blocked`, стадия `connect`).
- **Потоковые лимиты (D5):** чтение потоково (`client.stream`), счёт **переданных** и **распакованных** байтов, прерывание при превышении любого лимита (не `len(response.content)`); timeout connect/read/write/pool + общий deadline; ограничение параллелизма (`asyncio.Semaphore` на профиль). Рекомендованный механизм (ADR): counting-transport для raw + `aiter_bytes()` для decompressed (или `Accept-Encoding: identity` для HTML, где сжатие не требуется); точный механизм — за Builder, инвариант — обязателен.
- **Профили (D5/D6):** `html` — малый лимит (страница); `video` — загрузка на диск отдельным профилем, крупный лимит, совместимый с нынешними рабочими размерами (ориентиры baseline: `_DOWNLOAD_NATIVE_MAX_BYTES=2_000_000_000`, `YOUTUBE_MULTIMODAL_DOWNLOAD_TIMEOUT_SECONDS=240`, `_YTDLP_DOWNLOAD_TIMEOUT_SECONDS=900`); малый HTML-лимит к видео **не применяется**.
- **Ошибки/маскирование (D7):** `SafeFetchError(code, stage, reason, retryable)`; `code ∈ {scheme_not_allowed, credentials_in_url, destination_blocked, metadata_endpoint_blocked, redirect_blocked, too_many_redirects, too_many_bytes, decompressed_too_large, timeout, egress_guard_unavailable, ...}`; `stage ∈ {normalize, resolve, connect, redirect, stream, decompress}`. Маскирование секретных query-параметров (`key`,`api_key`,`token`,`sig`,`signature`,`x-api-key`…), cookies, proxy credentials — через существующий `sanitize()` до записи во все каналы; полный URL с query не логируется (scheme+host+path, query redacted).

### 4.2. Egress-контроль для подпроцессов (D4)
- **Pre-flight destination control:** любой пользовательский URL (yt-dlp/Cobalt/direct-download/media) проходит `guarded_target(url)` (нормализация + проверка назначения) **до** передачи клиенту.
- **Egress-guard (основной контроль при `MCA_EGRESS_GUARD_ENABLED` ON):** in-process **loopback** HTTP CONNECT/absolute-URI прокси, применяющий ту же destination-политику к каждому CONNECT-таргету; yt-dlp/transcript-api/медиа-подпроцессы маршрутизируются через него (`proxy`), включая redirects. При невозможности старта — видимое `egress_guard_unavailable`, остаётся pre-flight контроль (честный residual risk в отчёте); доверенные API/локальные службы не затрагиваются.
- **Cobalt (trusted local service):** URL валидируется при отправке (destination control); собственный egress Cobalt — вне процесса (отдельная конфигурация/документированное ограничение). Прокси-хосты также валидируются.
- `MCA_EGRESS_GUARD_ENABLED=false` → legacy (без egress-обвязки).

### 4.3. Доверенные API/локальные службы (D4)
- Отдельная env-only конфигурация (allowlist) `SAFE_FETCH_TRUSTED_HOSTS`/`SAFE_FETCH_TRUSTED_PORTS` (публичные API провайдеров + локальные службы: Cobalt `localhost:9000`, `LOCAL_BOT_API_URL`, Ollama, PG). Приватные/loopback-цели допускаются **только** для доверенных хостов и **никогда** для пользовательских URL. Глобальный запрет внутренней сети не ломает существующие интеграции.

### 4.4. Cookies/профиль (D8–D11)
- **Аудит потребителей (R17-safe, без значений):** `YOUTUBE_COOKIES_FILE` (env + hot `keys.youtube_cookies_file`), `cookiefile` (`build_ytdlp_base_opts`), `handlers/youtube.py`, `youtube_transcript_engine` (cookies + resident-proxy `keys.youtube_transcript_proxy_*`), `tools/video_downloader.py` (proxy/cookies/cobalt), `tools/cookies_export.py` (`--profile`/`--out`), volume mounts/внешние скрипты. Карта «потребитель→настройка→сценарий» — R17-safe evidence.
- **Упаковка:** исключить секретные runtime-данные из **новых** архивов/артефактов (`.gitignore`/правила сборки); исключение **не удаляет** файл на сервере; `git ls-files` не должен содержать cookies/профиль.
- **Перенос (если требуется):** копирование в закрытый runtime-каталог с сохранением владельца/прав и структуры профиля; обновление ссылок; проверка потребителей; оригинал остаётся до подтверждения.
- **Проверка video paths (A23):** субтитры, скачивание, транскрибация, итоговая выжимка — **включая реально используемый авторизованный сценарий** (не только публичный ролик).
- **Cleanup:** лишнюю копию удалять **только** после подтверждения работоспособности; иначе — `cleanup_deferred_dependency_unverified`, runtime-файлы остаются. Действующие сессии автоматически не отзываются; при подтверждённом раскрытии — сообщить владельцу, сохранив работоспособность. Значения секретов не помещать в отчёт.

### 4.5. Наблюдаемость и R17 (D12)
- События по `mca-13` (`start`+`outcome`) через REUSE `emit_mca_event`/`mca_events` (второй store запрещён), со стадией/причиной для блокировок назначения/лимитов/ошибок; регистрация стадий/виджет-ID для `mca-17a`; `reason_code` — расширяемый (SSRF/лимит/egress), `cleanup_deferred_dependency_unverified` (§17.2) для cookies.
- R17: `sanitize()` до записи; секреты не в логи/события/отчёт.

## 5. Δ DDL (санкция) / Δ каталога / kill-switch

- **Δ DDL = 0.** SafeFetcher/аудит cookies не требуют доменных таблиц: конфигурация — env-only, отчёт аудита — durable-документ (не БД), egress/лимиты — рантайм. Если Builder выявит необходимость durable-состояния — обязательна новая заявка @Architect и версия **v17+** через реестр `mca-14` (v16 занята `mca-03`); по умолчанию **0**.
- **Δ каталога = 0.** Рубильники/лимиты/allowlist — env-only `ClassVar`; `param_catalog.py` вне diff; F8 (ADR-1026-2) **NOT_APPLICABLE**.
- **Kill-switch (утверждены, env-only `ClassVar`, default ON, резолв per-call, OFF = паритет baseline):**
  - `MCA_SAFE_FETCH_ENABLED` — OFF: legacy-путь загрузки (как сейчас, без SSRF-обвязки/лимитов-обёртки).
  - `MCA_EGRESS_GUARD_ENABLED` — OFF: без эквивалентного egress-контроля для подпроцессов/yt-dlp/прокси (legacy).
- OFF фиксируется в release-manifest/логе с причиной/временем/планом (R17-safe); релиз — со всеми ON.

## 6. Приёмочные сценарии (SC)

- **SC-01:** разрешены только HTTP/HTTPS; URL нормализован; встроенные credentials запрещены (A22).
- **SC-02:** блокируются localhost/private/link-local/reserved и metadata-эндпоинты (**IPv4 и IPv6**).
- **SC-03:** проверяется каждый redirect и фактический адрес подключения (rebinding: предварительный DNS + независимый resolve недостаточны) (A22).
- **SC-04:** для медиа-подпроцессов/yt-dlp/прокси/обходящих клиентов — эквивалентный контроль назначения или egress; защита одного httpx-клиента не считается защитой процесса.
- **SC-05:** доверенные API и локальные службы имеют отдельную конфигурацию; глобальный запрет внутренней сети их не ломает.
- **SC-06:** потоковые лимиты переданных **и распакованных** байтов, timeout, параллелизм; большой stream блокируется **без полного чтения в RAM** (`len(content)` недостаточен) (A22).
- **SC-07:** крупное видео — отдельный профиль загрузки на диск, совместимый с нынешними размерами; HTML-лимит к видео не применяется.
- **SC-08:** ошибка возвращает код, стадию и понятную причину; секретные query/cookies/proxy credentials замаскированы (A22/A53).
- **SC-09:** карта потребителей cookies/профиля/mounts/скриптов собрана (R17-safe); секретные runtime-данные исключены из новых архивов **без удаления** на сервере; `git ls-files` чист.
- **SC-10:** при переносе — закрытый runtime-каталог с сохранением владельца/прав/структуры профиля; ссылки обновлены; потребители проверены.
- **SC-11:** video paths (субтитры/скачивание/транскрибация/выжимка) проверены на **авторизованном** сценарии; лишняя копия удаляется только после подтверждения, иначе `cleanup_deferred_dependency_unverified`; сессии автоматически не отзываются (A23).
- **SC-12:** значения секретов не попадают в отчёт; при подтверждённом раскрытии — уведомление владельца без потери работоспособности.
- **SC-13:** SafeFetcher подключён к фактическим потребителям (web/youtube/download/`fetch_article` через ToolResult); сеть вне транзакции записи; download-контракт ADR-1016-1 REUSE.
- **SC-14:** Δ DDL=0, Δ каталога=0; kill-switch env-only default ON; OFF = точный legacy-путь; deploy `DEFERRED_TO_RELEASE` (A28).
- **SC-15:** события `start`+`outcome` через `mca_events` со стадией/причиной; стадии/виджет-ID для `mca-17a`; R17 (A27/A53).

## 7. Тесты / деплой / откат

- **Тесты:** A22 (redirect на private IPv4/IPv6 и metadata; большой stream → блок без полного чтения в RAM; проверка каждого redirect/фактического адреса; маскирование секретов); A23 (video paths на авторизованном сценарии; cookies/профиль сохранены; `cleanup_deferred_dependency_unverified`); регрессии обычных ссылок/видео/доверенных API; OFF-паритет; pytest ≥ baseline, `git diff --check`=0.
- **Деплой:** `DEFERRED_TO_RELEASE` (§20). На `mca-release` — manifest (`config changes`: kill-switch/allowlist/лимиты), effective-state §20.2, проверка одного video path; cookies-отчёт §21.7 (R17-safe) — вход для `mca-release`.
- **Откат:** hot — `MCA_SAFE_FETCH_ENABLED=false`/`MCA_EGRESS_GUARD_ENABLED=false`; cold — `git revert` → `7165ff7` (DDL нет; cookies/профиль не затрагиваются откатом).

## 8. Документация / MEMORY

- Merge-раздел `plans/ARCHITECTURE.md` §97+ — по T-3814 (@Architect, только по Accepted).
- Рамка: `plans/docs/mca-round1027-arch-frames.md` §2 (Δ каталога), §3 (kill-switch), §1.2 (Δ DDL=0).
- KG/индекс — на @Memory (Step 10); MEMORY_DELTA в handoff.
