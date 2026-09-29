# `mca-02-safe-fetch-cookies` — evidence (Step 3 @Builder, T-3798…T-3813)

> **Статус:** 🟩 Реализовано + верифицировано (Builder). Ожидает независимого @Reviewer (T-3814).
> **Deploy:** `DEFERRED_TO_RELEASE` (§20; пер-фичевых деплоев/тегов/bump `APP_VERSION` нет).
> **Risk:** R3 (см. `threat-failure-analysis.md`).

## 1. Baseline → текущее состояние

| Параметр | Значение |
|---|---|
| HEAD / reviewed-commit | `05bc8704c2de5e7de1d5d04ac34df763d35219aa` (анкер отката `7165ff7`) |
| Ветка | `master`; рабочее дерево содержит незакоммиченные изменения волны 0 + `mca-03` (не трогали) |
| `APP_VERSION` | **2.58.31 (не менялся)** |
| SQLite DDL | **v16 (не менялся этой фичей; Δ DDL = 0)** |
| Δ каталога | **0** (`param_catalog.py` вне diff; F8 NOT_APPLICABLE) |
| `services/safe_fetch.py` | 1048 строк, sha256 `575941F8766995FB…` |
| Commits/теги | нет (по инструкции); `current_task.md`/`workflow_state.md`/`metrics.md`/`MEMORY.md` не изменялись |

## 2. Изменённые файлы

| Файл | Режим | Суть |
|---|---|---|
| `services/safe_fetch.py` | **NEW** | единый SafeFetcher: нормализация/схемы/credentials; SSRF-политика (IPv4/IPv6/private/link-local/CGNAT/ULA/reserved/multicast/metadata); ручные redirects + peer-проверка (`server_addr`); потоковые лимиты переданных+распакованных байтов; профили html/image/video (video — на диск); `SafeFetchError(code, stage, reason, retryable)`; `mask_url`/`mask_text`/`mask_query`; egress-guard (loopback CONNECT/absolute-URI прокси) + pre-flight `guard_subprocess_target`; env-allowlist доверенных хостов/портов; события MCA-13 `start`+`outcome` |
| `services/web_content_extractor.py` | **AMEND** | трафилатура-уровень через SafeFetcher (не второй fetcher); OFF → legacy `follow_redirects=True`/timeout 10.0 |
| `services/image_generation.py` | **AMEND** | `_download_bytes` → потоковый SafeFetcher (устранён анти-паттерн `len(content)` после полной загрузки); OFF → legacy |
| `services/youtube_transcript_engine.py` | **AMEND** | `ensure_egress_guard`; yt-dlp opts через egress-guard; transcript-api через loopback proxy (если resident-proxy не задан) |
| `tools/video_downloader.py` | **AMEND** | pre-flight пользовательского URL (`probe`/`download`/`download_ytdlp`/`download_direct`/`_request_tunnel`); Cobalt — trusted-валидация; клиент direct-stream и yt-dlp-подпроцесс через egress-guard |
| `config/settings.py` | **AMEND** | env-only `ClassVar`: `MCA_SAFE_FETCH_ENABLED`, `MCA_EGRESS_GUARD_ENABLED` (default ON); allowlist `SAFE_FETCH_TRUSTED_HOSTS/PORTS`; `SAFE_FETCH_UPSTREAM_PROXY`; лимиты/таймауты SafeFetcher |
| `services/mca_gates.py` | **AMEND** | резолверы `safe_fetch_enabled()`/`egress_guard_enabled()` + реестр kill-switch'ей |
| `services/mca_events.py` | **AMEND** | регистрация SSRF/лимит/egress `reason_code` в словаре §17.2 |
| `tests/test_mca02_safe_fetch_round1027.py` | **NEW** | 57 тестов: A22/A23, egress, R17, OFF-паритет, cookies |
| 5 × существующие тесты | **AMEND** | 2 новых теста паритета/egress + мок сетевого download (SafeFetcher) |

## 3. Приёмочные сценарии (фактическое покрытие)

### A22 — SSRF/redirect/лимиты
- Схемы/нормализация/credentials: `TestNormalize` (http/https only, IDN→punycode, dot-сегменты, порт, `file:`/`gopher:`/`data:`/userinfo).
- Блок private/loopback/link-local/CGNAT/ULA/multicast/unspecified/reserved/metadata IPv4 **и** IPv6 + IPv4-mapped: `TestDestination` (14 параметров).
- Redirect на private IPv4/IPv6/metadata: `test_redirect_to_private_ipv4_blocked`, `test_redirect_to_private_ipv6_blocked`, `test_redirect_to_metadata_blocked` (`redirect_blocked`, стадия `redirect`).
- Каждый redirect + фактический адрес: `test_peer_mismatch_blocked` (mismatch `server_addr` → `destination_blocked`, стадия `connect`), `test_peer_match_allowed`, `test_public_redirect_chain_allowed`, `test_too_many_redirects`.
- Большой stream без чтения в RAM: `test_large_stream_blocked_without_full_read` (32 MB генератор; прервано на <20 чанках; `too_many_bytes`).
- Декомпрессионная бомба: `test_decompressed_bomb_blocked` (gzip 5 MB→~5 KB, лимит распаковки → `decompressed_too_large`).
- Видео-профиль: `test_video_profile_has_large_limit` (2 ГБ; HTML-лимит не применён), `test_stream_to_file_video_profile`.
- Ошибка код/стадия/причина: `test_error_carries_code_stage_reason`.
- Маскирование: `test_mask_url_and_text`, `test_fetch_failure_event_no_secret`.
- Egress-контроль: `TestEgressGuard` (`_check` блок private/allow public; absolute-URI форвард; deny private; yt-dlp opts proxy/свой proxy).

### A23 — cookies/профиль
- `cleanup_deferred_dependency_unverified` зарегистрирован: `test_cleanup_deferred_code_registered`.
- `cookiefile` по-прежнему в yt-dlp opts, файл НЕ удалён: `test_cookiefile_still_wired_into_ytdlp_opts`.
- Presence-only диагностика без значений: `test_download_env_summary_presence_only`.
- Аудит потребителей/mounts/упаковки: `cookies-audit.md`; `git ls-files` чист (cookies/профиль не отслеживаются, `.gitignore` покрывает).

### Регрессии
- OFF-паритет: `test_off_parity_legacy_get` (web), gate-OFF в youtube/video тестах, `test_video_downloader_off_skips_preflight`, `test_apply_egress_to_ytdlp_opts`.
- Легитимные URL/видео: `test_legitimate_public_url_passes`, `test_public_redirect_chain_allowed`.
- Доверенные API: `test_trusted_public_api_not_broken`, `test_trusted_allowlist_permits_loopback`, `test_trusted_does_not_allow_metadata`.
- Kill-switch'и: `test_gates_default_on`, `test_all_safe_fetch_reason_codes_registered`.

## 4. Тесты (фактические числа)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest (`.venv`) | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | **9667 passed / 0 failed** (baseline 9608 + 59 новых) |
| Focused mca-02 | `pytest tests/test_mca02_safe_fetch_round1027.py -q` | **57 passed** |
| Затронутые модули | `pytest tests/test_web_content_extractor.py tests/test_image_generation_round1023.py tests/test_summary_cover_model_compat_round1024.py tests/test_video_download.py tests/test_youtube_transcript_engine.py tests/test_cookies_export.py -q` | все passed |
| JS vm-харнесс | `node tests/js/*.js` (47 файлов) | **47/47 ok** |
| Whitespace | `git diff --check` | exit 0 |

**Ручная проверка egress-guard (реальная сеть, httpx 0.28.1):** CONNECT-туннель
`https://example.com` через loopback-прокси → `200` (559 B); absolute-URI
`http://10.0.0.5/x` через тот же guard → `403 destination_blocked` (3/3 прогона);
чистый `stop()` guard'а без зависания (bounded `wait_closed`).

## 5. Δ DDL / Δ каталога / kill-switch

- **Δ DDL = 0** (`services/database.py` в этом шаге не менялся; v16 — от `mca-03`).
- **Δ каталога = 0** (`param_catalog.py` вне diff; env-only ClassVar).
- **Kill-switch (env-only, default ON, per-call, OFF = паритет baseline):**
  - `MCA_SAFE_FETCH_ENABLED` — OFF → legacy-путь загрузки;
  - `MCA_EGRESS_GUARD_ENABLED` — OFF → без egress-обвязки подпроцессов;
  - allowlist `SAFE_FETCH_TRUSTED_HOSTS`/`SAFE_FETCH_TRUSTED_PORTS`;
  - опциональный `SAFE_FETCH_UPSTREAM_PROXY`; лимиты/таймауты `SAFE_FETCH_*`.

## 6. Deploy / rollback (T-3813) — `DEFERRED_TO_RELEASE`

- **Manifest §20 (`config changes`):** kill-switch'и `MCA_SAFE_FETCH_ENABLED`/`MCA_EGRESS_GUARD_ENABLED` (default ON); allowlist/лимиты/таймауты — env-only (Δ каталога 0).
- **Effective-state:** при ON — SafeFetcher; OFF — точный legacy-путь (тесты паритета).
- **Rollback:** hot — env-OFF обоих рубильников; cold — `git revert` (DDL нет; cookies/профиль откатом не затрагиваются).
- **Cookies-отчёт §21.7 (R17-safe) — вход для `mca-release`:** зависимости сохранены (см. `cookies-audit.md`), из упаковки исключены `.gitignore`-правилами без удаления на сервере, намеренно не удалено (cleanup отложен), video paths проверены статически (live-часть — deferred).

## 7. Известные ограничения / не запускалось (для @Reviewer)

1. **Авторизованный video-сценарий live не проверялся** (нет доступа к реальным creds/аккаунту): runtime-cookies/профиль сохранены, закрыт `cleanup_deferred_dependency_unverified`; живая проверка субтитров/скачивания/транскрибации/выжимки — на `mca-release`.
2. **Egress-guard и `network_stream`:** anti-rebinding проверяется при наличии `extensions["network_stream"].get_extra_info("server_addr")` (httpx 0.28.1, httpcore — подтверждено на реальном соединении). MockTransport не даёт extension → статус `unverifiable` (WARN), продолжение; mismatch → блок (тест). В проде httpx даёт extension.
3. **Cobalt egress** — вне процесса (ADR-1027-5 D4): валидируется лишь отправляемый URL; исходящий контроль Cobalt — документированное ограничение.
4. **`download_direct`** — pre-flight + маршрутизация через egress-guard; peer-проверка не дублируется (guard = сетевой контроль).
5. **Реальный deploy** — не выполнялся (`DEFERRED_TO_RELEASE`).
6. **Browser-верификация** — NOT_APPLICABLE (фича backend/security; UI не меняет).
7. **Правки существующих тестов** (web/image/youtube/video): из-за перехода на SafeFetcher при ON добавлены моки/паритет-тесты; OFF-путь сохранён отдельными тестами.
8. **`_generate_get`** (`services/image_generation.py`) остаётся на legacy-пути: это GET-режим к **конфигурируемому доверенному** провайдеру (не пользовательский URL), с существующей пост-проверкой `len(content) > max_bytes`. Named-дефект §6.1 (`_download_bytes`) закрыт; перенос GET-режима на SafeFetcher — при необходимости в `mca-19`/follow-up (границы spec §1).

## 8. Правки тестов (сводно)

- `tests/test_web_content_extractor.py`: тест #1 → ON-путь (SafeFetcher, `Accept-Encoding: identity`); добавлен `test_off_parity_legacy_get`.
- `tests/test_image_generation_round1023.py`, `tests/test_summary_cover_model_compat_round1024.py`: сетевой download мокается (`_download_image_bytes`).
- `tests/test_video_download.py`: OFF-паритет + новый `test_probe_egress_guard_on_adds_proxy`.
- `tests/test_youtube_transcript_engine.py`: OFF-паритет egress-guard.
- Gate-патчи идут через `services.mca_gates.*` (устойчиво к `importlib.reload(config.settings)` в других тестах).

## 9. Rework round 10.27 (по итогам Reviewer gate, T-3814)

> Reviewer gate: **Needs Fixes** (`B-MCA02-1` High + M/L). High и non-blocking
> исправлены; требования не ослаблены (`APP_VERSION` без bump, Δ DDL/каталога = 0).

- **B-MCA02-1 — профильный timeout фактически не применялся.**
  `services/safe_fetch.py`: httpx 0.28 `Client.send` **не принимает** `timeout=`; значение передаётся в `build_request(..., timeout=prof.timeout)` (per-phase connect/read/write/pool). Дополнительно — общий deadline `asyncio.timeout(prof.timeout)` вокруг запроса+чтения в `fetch` и вокруг `_request`+записи в `stream_to_file` (гарантия возврата даже там, где per-phase таймаут не срабатывает). `_request`/`_read_stream` пробрасывают `httpx.TimeoutException` (не маскируют под `client_error`); `fetch`/`stream_to_file` переводят `TimeoutError`/`httpx.TimeoutException` в `SafeFetchError('safe_fetch_timeout', stage='stream', retryable=True)`.
  Тесты: `test_profile_timeout_enforced_fetch` (медленный транспорт 1.5 c, `timeout=0.2` → `safe_fetch_timeout`, возврат ≤0.6 c), `test_profile_timeout_enforced_stream_to_file`, `test_html_profile_keeps_baseline_timeout` (html=10 c, video=240 c — baseline сохранён).
- **M-MCA02-2 — trusted IP-литерал.** `guarded_target` для `trusted=True`+IP-литерала заполняет `resolved` канонизированным литералом (`ipaddress`), peer-проверка проходит. Тест `test_trusted_ip_literal_peer_match` (раньше → ложный `destination_blocked`).
- **M-MCA02-3 — trusted-HTTP путь.** Официальный путь `SafeFetcher.fetch(url, trusted=True)` (SSRF + лимиты + timeout) подтверждён `test_trusted_http_path_through_safe_fetcher`; расширение потребителей (`fetch_article`, Cobalt) — `mca-11`/`mca-19` (границы spec §1).
- **L-MCA02-4 — частичный файл.** `stream_to_file` при неуспехе удаляет `dest_path`. Тест `test_stream_to_file_removes_partial_on_limit`.

### Тесты (rework, факт)
| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest (`.venv`) | `python -m pytest -q -p no:cacheprovider` | **9678 passed / 0 failed** (baseline 9667 + 11 новых) |
| Focused mca-02 | `pytest tests/test_mca02_safe_fetch_round1027.py -q` | **63 passed** |
| Focused mca-02+mca-03+loader | `pytest tests/test_mca03_* tests/test_mca02_* tests/test_history_loader.py -q` | **94 passed** |
| JS vm-харнесс | `node tests/js/*.js` | **47/47 ok** |
