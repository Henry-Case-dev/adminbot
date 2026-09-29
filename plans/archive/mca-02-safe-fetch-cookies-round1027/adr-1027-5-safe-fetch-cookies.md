# ADR-1027-5 — `mca-02-safe-fetch-cookies`: общий SafeFetcher (HTTP/HTTPS, нормализация, запрет credentials; SSRF IPv4/IPv6/localhost/private/link-local/reserved/metadata; каждый redirect + фактический адрес подключения (anti-rebinding); эквивалентный egress/назначение для медиа-подпроцессов/yt-dlp/прокси; отдельная конфигурация доверенных API/локальных служб; потоковые лимиты переданных и распакованных байтов/timeout/параллелизм; отдельный видео-профиль на диск; ошибки код/стадия/причина + маскирование) и сохранение cookies/профиля (аудит, упаковка без удаления, перенос, проверка авторизованного video-сценария, cleanup-политика) — Δ DDL = 0, Δ каталога = 0, R3

- **Статус:** **Accepted** (факт Merge в `plans/ARCHITECTURE.md` **§97**, T-3814, 26.09.2026; см. §97.1–§97.6). На момент Step 2 — Proposed.
- **Фича:** `mca-02-safe-fetch-cookies` (Wave 1; независима от схемы identity). **Deploy:** `DEFERRED_TO_RELEASE`.
- **ТЗ-основание:** `plans/current_task.md` §6.1 (`:153–162`), §6.2 (`:170–178`), §2.15 (`:35`), §2.16/§17.3 (`:36`,`:838–846`), §3 (`:45–47`), §4 (`:99`), §19 A22/A23 (`:903–904`), §21.7 (`:1056`), §22 (`:1073–1074`); R17/R18.
- **Baseline:** HEAD `7165ff7`; `APP_VERSION` 2.58.31; SQLite DDL **v15**; каталог `473/430/448/102/100/21`; канон 12.
- **Связано:** AMEND `services/web_content_extractor.py`, `services/youtube_transcript_engine.py`, `tools/video_downloader.py`, `services/image_generation.py::_download_bytes`; REUSE `services/llm_probe.py::_safe_base` (паттерн SSRF), `write_transaction`/сеть-вне-tx (`mca-01`), `emit_mca_event`/`mca_events` (`mca-13`), download-контракт ADR-1016-1; потребители `mca-11`/`mca-19`; отчёт §21.7 — `mca-release`; рамка `plans/docs/mca-round1027-arch-frames.md`.

## Контекст

§6.1 требует общий SafeFetcher: только HTTP/HTTPS, нормализация URL, запрет встроенных credentials; проверка IPv4/IPv6/localhost/private/link-local/reserved и адресов инфраструктурных metadata-эндпоинтов; проверка **каждого** redirect и **фактически используемого адреса подключения** (простая предварительная DNS-проверка с последующим независимым resolve недостаточна против rebinding); эквивалентный контроль назначения или сетевой egress для медиа-подпроцессов, yt-dlp, прокси и обходящих SafeFetcher клиентов (защита одного httpx-клиента не защищает весь процесс); отдельная конфигурация доверенных API провайдеров и локальных служебных соединений (не ломать глобальным запретом внутренней сети); потоковое чтение с лимитом **переданных и распакованных** байтов, timeout и ограничением параллелизма (`len(response.content)` после полной загрузки недостаточен); отдельный профиль загрузки крупного видео на диск, совместимый с нынешними рабочими размерами (маленький HTML-лимит к видео не применяется); ошибка возвращает код/стадию/понятную причину; секретные query-параметры, cookies и proxy credentials маскировать. §6.2 требует аудита потребителей cookies/профиля/mounts/скриптов; исключения секретов из новых архивов без удаления на сервере; переноса в закрытый runtime-каталог с сохранением владельца/прав; проверки субтитров/скачивания/транскрибации/выжимки на реально используемом авторизованном сценарии; удаления лишней копии только после подтверждения, иначе `cleanup_deferred_dependency_unverified`; без автоматического отзыва сессий; без значений секретов в отчёте.

**Фактическое состояние baseline (сверено с рабочей веткой):** `web_content_extractor.py` — `httpx.AsyncClient` с `follow_redirects=True`, без SSRF; `image_generation._download_bytes` читает `response.content` целиком и лишь затем проверяет размер; yt-dlp/transcript-api/Cobalt работают без dest-контроля/egress; `llm_probe._safe_base` — существующий минимальный SSRF-паттерн (REUSE паттерна); cookies/профиль разнесены по `settings`/hot-настройкам/`cookies_export`/yt-dlp-опциям без формализованного аудита и cleanup-политики. Все дефекты §6 присутствуют.

## Решения

**D1. Единый SafeFetcher вместо второго fetcher.**
- **Выбрано:** новый модуль `services/safe_fetch.py` как **общий** SafeFetcher; `services/web_content_extractor.py` AMEND → использует его; потребители (web/youtube/download/`fetch_article`/image) ходят через контракт SafeFetcher. Второй независимый fetcher запрещён.
- **Обоснование:** §6.1 «создать или расширить общий SafeFetcher»; §3 REUSE.
- **Альтернатива:** расширить только `web_content_extractor` — отклонено (не покрывает media/subprocess/image).

**D2. Нормализация URL, схемы, запрет credentials.**
- **Выбрано:** схема только `http`/`https`; host lowercase/IDN→punycode; удаление default-порта и dot-сегментов; запрет userinfo/встроенных credentials; запрет control-символов/backslash; отклонение прочих схем (`file:`/`gopher:`/`ftp:`/`data:`…). Хост — через `urlsplit` (не `startswith`; REUSE паттерна `llm_probe._safe_base`).
- **Обоснование:** §6.1 verbatim (`:155`).

**D3. SSRF-проверки + anti-rebinding.**
- **Выбрано:** resolve A/AAAA и блокировка loopback/private/link-local/CGNAT/ULA/multicast/unspecified/reserved/broadcast, IPv4-mapped IPv6 и metadata-эндпоинтов (IPv4 **и** IPv6). `follow_redirects=False` + ручной цикл redirect (≤5), повторная нормализация/проверка каждого шага; после подключения — проверка **фактического** peer-адреса через `response.extensions["network_stream"].get_extra_info("server_addr")` (подтверждено для httpx ≥0.21/httpcore; установлен httpx 0.28.1) на `client.stream(...)`; несовпадение → блок (`destination_blocked`, стадия `connect`).
- **Обоснование:** §6.1 verbatim (`:156–157`); anti-rebinding обязателен.
- **Механизм (сверено, источник):** httpx docs «Extensions → network_stream → get_extra_info("server_addr")»; encode/httpx discussion #2633/#1569. Ограничение: peer известен только при открытом соединении — поэтому `stream` и проверка до чтения тела.

**D4. Egress/назначение для подпроцессов + доверенные API.**
- **Выбрано:** (a) pre-flight destination control для любого пользовательского URL до передачи yt-dlp/Cobalt/direct-download/media; (b) при `MCA_EGRESS_GUARD_ENABLED` ON — in-process **loopback** HTTP CONNECT/absolute-URI прокси, применяющий ту же политику к каждому CONNECT-таргету, через который маршрутизируются медиа-подпроцессы/yt-dlp/transcript-api (включая redirects); при недоступности — `egress_guard_unavailable` + честный residual risk; (c) доверенные API/локальные службы — отдельный env-only allowlist (`SAFE_FETCH_TRUSTED_HOSTS`/`SAFE_FETCH_TRUSTED_PORTS`), приватные/loopback-цели только для них и никогда для пользовательских URL; Cobalt остаётся trusted local service (его egress — вне процесса, документированное ограничение).
- **Обоснование:** §6.1 verbatim (`:158–159`); §4 (без новой инфраструктуры — loopback/in-process).
- **Альтернатива:** только pre-flight без egress — отклонено как недостаточное против redirects внутри subprocess; только egress без pre-flight — отклонено (defense-in-depth).

**D5. Потоковые лимиты и параллелизм.**
- **Выбрано:** `client.stream` с потоковым счётом переданных **и** распакованных байтов и прерыванием при превышении любого лимита (не post-hoc `len(content)`); timeout connect/read/write/pool + общий deadline; `asyncio.Semaphore` на профиль. Рекомендованный механизм: counting-transport для raw + `aiter_bytes()` для decompressed (либо `Accept-Encoding: identity` для HTML); точную реализацию выбирает Builder, инвариант «оба лимита + без полного чтения в RAM» обязателен.
- **Обоснование:** §6.1 verbatim (`:160`); A22.

**D6. Профили загрузки (HTML vs video-диск).**
- **Выбрано:** `html`-профиль — малый лимит (страница); `video`-профиль — загрузка **на диск** с крупным лимитом, совместимым с нынешними рабочими размерами (ориентиры: 2 ГБ native / 240 c multimodal / 900 c yt-dlp); малый HTML-лимит к видео не применяется.
- **Обоснование:** §6.1 verbatim (`:161`); сохранить текущие рабочие размеры.

**D7. Ошибки и маскирование.**
- **Выбрано:** `SafeFetchError(code, stage, reason, retryable)`; коды/стадии — перечислимы (SC-08); `sanitize()` до записи во все каналы; секретные query/cookies/proxy credentials маскируются; полный URL с query не логируется.
- **Обоснование:** §6.1 verbatim (`:162`); §17.3; R17.

**D8. Аудит cookies/профиля.**
- **Выбрано:** карта «потребитель→настройка→сценарий» (R17-safe) по env/hot/`cookiefile`/профилю/mounts/внешним скриптам; REUSE существующих настроек; не удалять и не отзывать.
- **Обоснование:** §6.2 verbatim (`:172`); §2.15.

**D9. Упаковка и перенос.**
- **Выбрано:** исключение секретных runtime-данных из новых архивов/артефактов **без удаления** на сервере (`.gitignore`/правила сборки; `git ls-files` чист); при необходимости переноса — закрытый runtime-каталог с сохранением владельца/прав/структуры профиля, обновление ссылок, проверка потребителей; оригинал до подтверждения.
- **Обоснование:** §6.2 verbatim (`:173–174`).

**D10. Проверка video paths и cleanup-политика.**
- **Выбрано:** проверка субтитров/скачивания/транскрибации/выжимки на **авторизованном** сценарии; удаление лишней копии только после подтверждения, иначе `cleanup_deferred_dependency_unverified` (§17.2); сессии автоматически не отзываются; при подтверждённом раскрытии — уведомление владельца без потери работоспособности; значения секретов не в отчёт.
- **Обоснование:** §6.2 verbatim (`:175–178`); A23.

**D11. Δ DDL / Δ каталога.**
- **Выбрано:** Δ DDL = **0** (конфигурация env-only, отчёт — durable-документ, egress/лимиты — рантайм); Δ каталога = **0** (env-only `ClassVar`, F8 NOT_APPLICABLE). При появлении durable-потребности — новая заявка и версия **v17+** через реестр `mca-14` (v16 — `mca-03`).
- **Обоснование:** §18; ADR-1026-2; рамка §1.2.

**D12. Kill-switch, наблюдаемость, границы.**
- **Выбрано:** `MCA_SAFE_FETCH_ENABLED` (OFF → legacy fetch без SSRF/лимитов-обёртки), `MCA_EGRESS_GUARD_ENABLED` (OFF → без egress-обвязки подпроцессов); env-only `ClassVar`, default ON, резолв per-call, OFF = паритет baseline. События через `mca_events`; стадии/виджет-ID для `mca-17a`. Границы: `mca-11` (ToolResult/`fetch_article`), `mca-19` (vision bytes/MIME/декомпрессия) — не дублировать; отчёт §21.7 — `mca-release`; download-контракт — REUSE ADR-1016-1.
- **Обоснование:** §18 `:872`; §17.1–§17.3; §4; §3 REUSE.

## Санкции и вердикты

- **Δ DDL = 0.** При новой durable-потребности — отдельная заявка @Architect, версия **v17+** через реестр `mca-14`.
- **Δ каталога = 0**; F8 (ADR-1026-2) **NOT_APPLICABLE**.
- **Kill-switch:** `MCA_SAFE_FETCH_ENABLED`, `MCA_EGRESS_GUARD_ENABLED` (env-only, default ON, OFF-паритет baseline).
- **Политика доверенных API/egress:** env-only allowlist `SAFE_FETCH_TRUSTED_HOSTS`/`SAFE_FETCH_TRUSTED_PORTS`; egress-guard — loopback/in-process; Cobalt — trusted local service с валидацией отправляемого URL.
- **reason_code:** REUSE/расширение (SSRF/лимит/egress) + `cleanup_deferred_dependency_unverified` (§17.2).
- **Risk:** **R3** (безопасность внешних загрузок + сохранность авторизации видео); `threat-failure-analysis.md` обязателен (Блок H). Понижение — при зелёных A22/A23 и доказанном egress-контроле на фактическом diff.
- **Обратный путь:** hot env-OFF; cold `git revert` → `7165ff7`; DDL нет; cookies/профиль откатом не затрагиваются.
- **Release policy:** `DEFERRED_TO_RELEASE`.

## AMEND / REUSE-карта

| Артефакт | Режим | Суть |
|---|---|---|
| `services/safe_fetch.py` | **NEW (общий)** | нормализация/SSRF/redirect/peer-проверка/лимиты/профили/ошибки |
| `services/web_content_extractor.py` | **AMEND** | использует SafeFetcher (не второй fetcher) |
| `services/youtube_transcript_engine.py` | **AMEND** | destination control/egress для yt-dlp/transcript-api |
| `tools/video_downloader.py` | **AMEND** | guarded target/egress; REUSE download-контракт ADR-1016-1 |
| `services/image_generation.py::_download_bytes` | **AMEND** | потоковые лимиты вместо `len(content)` |
| `services/llm_probe.py::_safe_base` | **REUSE (паттерн)** | хост через `urlsplit`; не дублировать |
| `config/settings.py` (cookies/proxy/`cookiefile`) | **REUSE** | не удалять/не отзывать; env-only |
| `tools/cookies_export.py` | **REUSE/AMEND** | аудит профиля/упаковка |
| `emit_mca_event`/`mca_events` (`mca-13`) | **REUSE** | события; второй store запрещён |
| `mca-11`/`mca-19` | **Unblocks/consumers** | ToolResult/vision поверх контракта |

| Решение | Задачи |
|---|---|
| D1 (единый SafeFetcher) | T-3802, T-3806 |
| D2 (нормализация/credentials) | T-3802 |
| D3 (SSRF/rebinding) | T-3803 |
| D4 (egress/доверенные API) | T-3804, T-3806, T-3812 |
| D5 (потоковые лимиты) | T-3804, T-3810 |
| D6 (видео-профиль) | T-3804 |
| D7 (ошибки/маскирование) | T-3805 |
| D8 (аудит cookies) | T-3807 |
| D9 (упаковка/перенос) | T-3808 |
| D10 (video paths/cleanup) | T-3809, T-3813 |
| D11 (Δ DDL/каталог) | T-3800 |
| D12 (kill-switch/границы) | T-3806, T-3811, T-3812, T-3813 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Где SafeFetcher | только `web_content_extractor`; общий модуль | **общий `safe_fetch.py`** | покрыть media/subprocess/image |
| Anti-rebinding | повторный resolve; peer-проверка | **peer-проверка `server_addr`** | §6.1; httpx API подтверждён |
| Egress подпроцессов | только pre-flight; egress-guard | **pre-flight + loopback guard** | defense-in-depth; без инфры |
| Лимиты | `len(content)`; потоково | **потоково, оба счётчика** | §6.1 verbatim |
| Видео | общий HTML-лимит; отдельный дисковый профиль | **отдельный профиль** | §6.1 verbatim |
| Cookies cleanup | удалить сразу; только после подтверждения | **после подтверждения / deferred** | §6.2; A23 |
| Δ DDL | таблица кеша/eгress; 0 | **0** (v17+ при необходимости) | конфигурация env-only |
| Kill-switch | каталожный; env-only | **env-only ClassVar** | Δ каталога=0 |
| Risk | R2; R3 | **R3** | безопасность + сохранность авторизации |

## Последствия

- §6.1: общий SafeFetcher (схемы/нормализация/credentials; SSRF IPv4+IPv6/metadata; каждый redirect + фактический адрес; egress для подпроцессов/прокси; отдельная конфигурация доверенных API; потоковые лимиты/распаковка/timeout/параллелизм; видео-профиль; ошибки со стадией/причиной; маскирование).
- §6.2: cookies/профиль сохранены; аудит/упаковка без удаления; перенос в закрытый каталог; проверка авторизованного video-сценария; cleanup только после подтверждения (`cleanup_deferred_dependency_unverified`); сессии не отзывать; секреты не в отчёт.
- Δ DDL=0; Δ каталога=0; risk R3 + threat-артефакт; hot-откат env-OFF; cold — `git revert` → `7165ff7`; deploy `DEFERRED_TO_RELEASE`.

## Ссылки

- Feature: `plans/features/mca-02-safe-fetch-cookies/{spec.md, tasks.md, adr-1027-5-safe-fetch-cookies.md}`.
- Рамка: `plans/docs/mca-round1027-arch-frames.md` (§2 Δ каталога, §3 kill-switch, §1.2 Δ DDL=0).
- Код: `services/web_content_extractor.py` (`:40–171`); `services/youtube_transcript_engine.py` (`:70–160`, `:377–421`); `tools/video_downloader.py` (`:303–337`); `services/image_generation.py` (`:825–887`); `services/llm_probe.py` (`:166–188`); `config/settings.py` (`:1179`, `:1629–1631`, `:1985–2018`); `tools/cookies_export.py` (`:70–146`); `handlers/youtube.py` (`:268`).
- ТЗ: `plans/current_task.md` §6.1 (`:153–162`), §6.2 (`:164–178`), §17.3 (`:838–846`), §19 A22/A23 (`:903–904`), §21.7 (`:1056`), §22 (`:1073–1074`).
- Внешний источник (механизм): httpx Extensions doc — `network_stream` → `get_extra_info("server_addr")`; установленная версия httpx **0.28.1** (сверено).
- Архитектура: merge → §97+; входы — §94 (`mca-13`), §95 (`mca-01`); ADR-1016-1 (download-контракт, REUSE).
- Точка отката: коммит `7165ff7`.
