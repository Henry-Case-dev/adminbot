# `mca-02-safe-fetch-cookies` — threat & failure analysis (R3, ADR-1027-5 D3–D10)

> **Причина R3:** безопасность внешних загрузок (SSRF/rebinding/декомпрессионные
> бомбы) и сохранность авторизации видеосервисов. Ошибка может открыть внутреннюю
> сеть либо разлогинить/сломать production video-pipeline. Артефакт обязателен
> (spec §Risk; Блок H).

## 1. Границы и активы

- **Активы:** внутренняя сеть/loopback/метаданные облака; cookies/браузерный профиль
  YouTube; resident/гео-прокси креды; скачиваемые медиа-файлы; MCA-13 событие-стор.
- **Вне scope:** provenance (`mca-04a`), retrieval/age (`mca-07`), vision bytes/MIME
  (`mca-19`), ToolResult/цепочки (`mca-11`), egress самого Cobalt (документированное
  ограничение), cookies-отчёт §21.7 (`mca-release`).

## 2. Модель угроз (R17: секреты/полные URL не логируются)

| # | Угроза | Вектор | Мера | Остаточный риск |
|---|---|---|---|---|
| T1 | SSRF на внутреннюю сеть | пользовательский URL → private/loopback | `guarded_target` (resolve A/AAAA, блок private/loopback/link-local/CGNAT/ULA/reserved/multicast/unspecified/broadcast) | Low |
| T2 | Обход через redirect | 302 на private/metadata | ручной цикл redirect (≤5), каждая цель нормализуется+проверяется заново | Low |
| T3 | DNS-rebinding | смена IP между проверкой и connect | peer-проверка фактического `server_addr` после открытия потока | Low |
| T4 | Metadata credentials | 169.254.169.254 / fd00:ec2::254 / 100.100.100.200 / `metadata.google.internal` | блок по IP и по имени, **даже для trusted** | Low |
| T5 | Декомпрессионная бомба | gzip/br с малым wire-размером | лимит **распакованных** байтов потоково + `Accept-Encoding: identity` | Low |
| T6 | Переполнение RAM/диска | огромный поток | `aiter_bytes` чанками; лимит переданных+распакованных; HTML-лимит к видео не применяется | Low |
| T7 | Subprocess SSRF (yt-dlp/медиа) | обход httpx-контура | pre-flight `guard_subprocess_target` + loopback egress-guard (CONNECT/absolute-URI) | Medium (Cobalt egress вне процесса; при недоступности guard — `egress_guard_unavailable` + pre-flight) |
| T8 | Поломка локальных служб глобальным запретом | Cobalt/Ollama/PG | отдельный env-allowlist `SAFE_FETCH_TRUSTED_HOSTS/PORTS`; приватные цели только для trusted, никогда для user-URL | Low |
| T9 | Утечка cookies/proxy-кред в логи/события/отчёт | логирование URL/кредов | `sanitize()` + `mask_url`/`mask_text`; presence-only диагностика; значения не в отчёт | Low |
| T10 | Потеря авторизации видео | удаление cookies/профиля/отзыв сессий | файлы не удаляются; cleanup только после подтверждения; иначе `cleanup_deferred_dependency_unverified` | Low (deferred live-check) |
| T11 | Секреты в артефактах сборки | cookies/профиль в git/архиве | `.gitignore`-правила; `git ls-files` чист; исключение ≠ удаление | Low |

## 3. Модель отказов (failure modes)

| F | Отказ | Наблюдаемый эффект | Обработка | Проверка |
|---|---|---|---|---|
| F1 | DNS transient-сбой | ложная блокировка легитимного URL | pre-flight в video-пути не блокирует на `resolve_failed` (фактический запрос/egress-guard решает) | `test_video_downloader_off/on` |
| F2 | Guard не стартует | нет loopback-прокси | `egress_guard_unavailable` (WARN-событие) + остаётся pre-flight (residual risk) | `test_apply_egress_to_ytdlp_opts` |
| F3 | Свой proxy задан | гео-доступ ломается guard'ом | guard **не перезаписывает** существующий `proxy`; только destination control | `test_apply_egress_to_ytdlp_opts` |
| F4 | Metadata при trusted | allowlist «доверяет» metadata | metadata блокируется безусловно | `test_trusted_does_not_allow_metadata` |
| F5 | OFF kill-switch | legacy-путь | `MCA_SAFE_FETCH_ENABLED`/`MCA_EGRESS_GUARD_ENABLED` OFF = паритет baseline | `test_off_parity_legacy_get`, gate-OFF тесты |
| F6 | Большой stream | OOM/латентность | потоковые лимиты, прерывание без полного чтения | `test_large_stream_blocked_without_full_read` |
| F7 | gzip-бомба | распаковка сверх лимита | `decompressed_too_large` | `test_decompressed_bomb_blocked` |
| F8 | Peer невидим (MockTransport/Chunked) | anti-rebinding не проверяется | `unverifiable` → WARN, продолжение (pre-resolution работает); в проде httpx даёт `network_stream` | `test_peer_mismatch_blocked`, `test_peer_match_allowed` |
| F9 | Cookies/профиль нужны для авторизации | поломка скачивания/субтитров | файлы сохранены; live-check отложен, cleanup не выполняется | `cookies-audit.md`; `test_cookiefile_still_wired_into_ytdlp_opts` |

## 4. Наблюдаемость (D12)

- События `start`+terminal `outcome` через `emit_mca_event`/`mca_events` (единственный
  durable-стор, второй запрещён). `reason_code` зарегистрированы в §17.2:
  `destination_blocked`, `metadata_endpoint_blocked`, `redirect_blocked`,
  `too_many_redirects`, `resolve_failed`, `too_many_bytes`, `decompressed_too_large`,
  `safe_fetch_timeout`, `egress_guard_unavailable`, `scheme_not_allowed`,
  `credentials_in_url`, `invalid_url`, `client_error` (+ `cleanup_deferred_dependency_unverified`).
- R17: события идут через `sanitize()`; сырой URL с query не передаётся — только host
  (`entity_id`).

## 5. Остаточные риски / передача

- **Cobalt egress** — вне процесса (ADR-1027-5 D4); его собственный исходящий контроль
  документирован как ограничение. Валидируется лишь отправляемый в Cobalt пользовательский URL.
- **Guard недоступен** — `egress_guard_unavailable`, остаётся pre-flight (честный residual).
- **Direct in-process stream** (`tools/video_downloader.download_direct`) — pre-flight +
  маршрутизация через egress-guard; peer-проверка не выполняется отдельно (guard = сетевой контроль).
- **Авторизованный video-сценарий** (субтитры/скачивание/транскрибация/выжимка) live не
  проверялся (нет доступа к реальным creds/аккаунту) → `cleanup_deferred_dependency_unverified`,
  runtime-файлы сохранены; проверка — на `mca-release`.
- **Триггеры понижения R3→R2** (spec §Risk): подтверждённая блокировка private/internal для
  всех путей (есть: T1–T4 на фактическом diff), эквивалентный egress-контроль для подпроцессов
  (есть: pre-flight + loopback guard, residual по Cobalt), зелёные A22/A23 на фактическом diff
  (A22 — зелёный; A23 — статическая часть зелёная, live-часть deferred).

## 6. Rework round 10.27 (по итогам Reviewer gate: B-MCA02-1, M-MCA02-2/-3, L-MCA02-4)

| # | Угроза/отказ | Вектор | Мера (после фикса) | Проверка |
|---|---|---|---|---|
| F10 | Зависание на медленном/чёрном сервере | профильный `timeout` объявлен, но не передавался в транспорт (`timeout=None`) | per-request `build_request(..., timeout=prof.timeout)` + общий deadline `asyncio.timeout(prof.timeout)` в `fetch`/`stream_to_file`; `httpx.TimeoutException`/`TimeoutError` → `safe_fetch_timeout` (stage `stream`) | `test_profile_timeout_enforced_fetch`, `test_profile_timeout_enforced_stream_to_file` |
| T12 | Ложный блок доверенной IP-литерал цели | `resolved=()` при IP-литерале → peer mismatch | для `trusted`+IP-литерала `resolved` заполняется канонизированным литералом | `test_trusted_ip_literal_peer_match` |
| T13 | Отсутствие официального trusted-HTTP пути | только pre-flight + ручной httpx | `SafeFetcher.fetch(..., trusted=True)` — официальный путь (SSRF + лимиты + timeout); потребители расширяют в `mca-11`/`mca-19` | `test_trusted_http_path_through_safe_fetcher` |
| F11 | Частичный файл на диске при ошибке | прерывание `stream_to_file` по лимиту | `unlink(dest_path)` при неуспехе (L-MCA02-4) | `test_stream_to_file_removes_partial_on_limit` |

**Регрессия baseline:** html-профиль сохраняет прежние 10 с (`SAFE_FETCH_HTML_TIMEOUT_SECONDS`),
video — 240 с (`test_html_profile_keeps_baseline_timeout`).
