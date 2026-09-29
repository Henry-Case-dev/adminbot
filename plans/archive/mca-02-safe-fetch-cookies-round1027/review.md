# `mca-02-safe-fetch-cookies` — независимый Reviewer gate (T-3814, round 10.27 / Wave 1) — итерация 2

> **Статус:** 🟩 **Approved** (0 Critical, 0 High, 0 блокирующих Medium; 1 Low watch-item общий с волной).
> **Итерация:** 2 — точечный re-review после rework (T-3814-R1…R4). Итерация 1 — 🟥 `Needs Fixes` (B-MCA02-1 High).
> **Единый gate:** обе линзы (requirements/correctness + focused change audit); Scanner отсутствует (прецедент Эпик 3 / волны 0).
> **Risk-Level:** **R3** (ратифицировано: SSRF/rebinding/декомпрессионные бомбы + сохранность авторизации видеосервисов). `threat-failure-analysis.md` присутствует и проверен.
> **Deploy:** `DEFERRED_TO_RELEASE` (§20). Δ DDL = 0, Δ каталога = 0.

## Binding (точное ревьюируемое состояние, итер. 2)

| Параметр | Значение |
|---|---|
| `Reviewed-Commit` | `05bc8704c2de5e7de1d5d04ac34df763d35219aa` (HEAD; код-анкер `7165ff7`) |
| `Working-Tree-Hash` | `09f2d9e942909a4240d4ef3c9e25b458e08eb9d1d83da562477d917286e1f8e0` |
| `Tracked-Diff-SHA256` (`git diff --no-color`) | `72b00db0025e7cb14dc655ef484305a5e23644134dda62a4d97acb48a607c8eb` |
| `Spec-Hash` (не менялся rework'ом) | `d31f6929e54fd99e08e86c9d8640ef4e59182c62d583505efb347814877fb482` |
| `ADR-Hash` (не менялся) | `1c9936a4113d37e7e698b6e1e63b758af11fc956c33162f5462e275d664d7962` |
| `Tasks-Hash` (обновлён: Блок I rework) | `4f91480723dd9d70e4f4d90015eab92b78ab83cb628df83aa22403f624c6c506` |
| `Evidence-Hash` | `bb5e2d030b565586af8959d0c1fc58fb1428c193908e93f79105b4b168f5a232` |
| `Threat-Hash` | `08c330d1e13aa672034c1b80c9a3941411fb377c3d1f3606c7448e20cd39c5b3` |
| `Cookies-Audit-Hash` | `0a7d3a4cb31a797a66233cc00f887d544eb2c09fb0d5e13896f9d44f9777de63` |
| Git base | `05bc870` → рабочее дерево (изменения **НЕ закоммичены**, DEFERRED_TO_RELEASE); staged-контент отсутствует |
| Diff scope | `services/safe_fetch.py` (NEW), `services/web_content_extractor.py`, `services/image_generation.py`, `services/youtube_transcript_engine.py`, `tools/video_downloader.py`, `config/settings.py`, `services/mca_gates.py`, `services/mca_events.py`, `tests/test_mca02_*`, `cookies-audit.md` |

**Рецепт Working-Tree-Hash:** единый с `mca-03/review.md` (итер. 2): `sha256("HEAD <rev>\n" + "TRACKED_DIFF_SHA256 <sha256(git diff --no-color)>\n" + "U <path> <sha256(content)>"` для untracked-не-`node_modules` файлов, отсортированных по path, **без review-артефактов** волны 1; wave-0-конвенция. Оба фичи делят один хэш рабочего дерева.

**Сверка с Builder:** полный манифест (включая review-артефакты итер. 1) = `2ac636a7…`; заявленный Builder `bae421c5…` не воспроизводится (см. L-W1-1 в сводке волны) — binding пересчитан Reviewer'ом и является авторитетным.

## Checks performed (независимо, итер. 2)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest (`.venv`) | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | **9678 passed / 0 failed** (192.24s) ✔ |
| Focused mca-02 | `pytest tests/test_mca02_safe_fetch_round1027.py -q` | **63 passed** ✔ |
| Focused mca-03+mca-02 | `pytest tests/test_mca03_* tests/test_mca02_* -q` | **88 passed** ✔ |
| JS vm-харнесс | 47 файлов `tests/js/*.js` + `node --check web/app.js` | **47/47 ok**; app.js check exit 0 ✔ |
| Whitespace | `git diff --check` | exit 0 ✔ |
| httpx | импорт | **0.28.1** ✔ |
| Cookies `git ls-files` | cookies/профиль не отслеживаются (только `tools/cookies_export.py`, `tests/test_cookies_export.py`) | чисто ✔ |
| Δ каталога | `param_catalog.py`/F8 fixture не изменены | ✔ |
| `APP_VERSION` | 2.58.31 | не менялся ✔ |

## Re-check блокирующего finding (итер. 1 → итер. 2)

### [B-MCA02-1] High → **CLOSED** — профильный timeout реально применяется

- **Код:** `services/safe_fetch.py:535–541` — `http.build_request(..., timeout=profile.timeout)` (per-phase connect/read/write/pool через `request.extensions["timeout"]`; httpx 0.28 `send` не принимает `timeout=`, поэтому значение задаётся на `build_request`); `:598` — общий deadline `asyncio.timeout(prof.timeout)` вокруг `_request`+чтения в `fetch`; `:689` — тот же deadline в `stream_to_file`; `:607–611` и `:722–726` — `TimeoutError`/`httpx.TimeoutException` → `SafeFetchError("safe_fetch_timeout", stage="stream", retryable=True)`; `_request`/`_read_stream` пробрасывают таймауты, не маскируя под `client_error` (`:545–546`, `:636–644`).
- **Воспроизведение:** `test_profile_timeout_enforced_fetch:291–307` — медленный транспорт 1.5 c, `fetch(timeout=0.2)` → `safe_fetch_timeout` (stage `stream`), возврат **≤0.6 c**; `test_profile_timeout_enforced_stream_to_file:309–327` — то же для выгрузки на диск + `assert not dest.exists()` (частичный файл удалён); `test_html_profile_keeps_baseline_timeout:329–332` — html=10.0 c, video=240.0 c (baseline не ослаблен). Все три — passed в моём прогоне.
- **Мой независимый разбор семантики:** per-request timeout покрывает per-phase лимиты на реальном транспорте httpx; жёсткий `asyncio.timeout` гарантирует возврат даже там, где кастомный/Mock-транспорт игнорирует расширение таймаута (именно этот сценарий в тесте — «вернулся за профильный timeout»). Ранее заявленные, но мёртвые `SAFE_FETCH_HTML_TIMEOUT_SECONDS=10`/video=240 теперь действуют. Регресс относительно baseline для html закрыт; sc timeout (SC-06) выполнен.
- **Вердикт:** finding закрыт.

## Dispositions Medium/Low (итер. 2)

| ID | Итер.1 | Итог итер. 2 | Ссылки / тест |
|---|---|---|---|
| M-MCA02-2 (`trusted=True` + IP-литерал) | OPEN | **CLOSED** — `guarded_target:364–373` для trusted+литерала канонизирует `resolved=(str(ip_address(host)),)` (resolve пропускается, peer-проверка больше не даёт ложный mismatch) | `test_trusted_ip_literal_peer_match:361–371` (`resolved == ("127.0.0.1",)`, fetch ok) |
| M-MCA02-3 (нет trusted-HTTP через SafeFetcher) | OPEN | **CLOSED как путь + carry-over** — официальный `SafeFetcher.fetch(url, trusted=True)` подтверждён; расширение потребителей (Cobalt/`fetch_article`) — границы `mca-11`/`mca-19`, зарегистрировано в `tasks.md` T-3814-R3 | `test_trusted_http_path_through_safe_fetcher:373–382`; границы spec §1 |
| L-MCA02-4 (`stream_to_file` не чистит частичный файл) | OPEN | **CLOSED** — флаг `failed` + `os.unlink(dest_path)` в `finally` (`safe_fetch.py:685–735`) | `test_stream_to_file_removes_partial_on_limit:334–344` и `..._stream_to_file` (dest не существует) |

Побочных поломок не найдено: единственный `http.send` в модуле идёт после `build_request` с timeout (`safe_fetch.py:543`); `fetch_json` использует профильный default; consumers не меняют сигнатуры; OFF-пути consumers сохранены (паритет-тесты в полном прогоне).

## Новые findings (итер. 2)

Новых блокирующих/открытых findings нет. Единственное замечание — общеволновое **[L-W1-1] Low (doc/binding)** о невоспроизводимости Builder-reported `wt` (см. `mca-wave1-review.md`); на продукт не влияет.

## OFF-паритет kill-switch

- `MCA_SAFE_FETCH_ENABLED=false` → legacy-путь загрузки consumers (паритет baseline): `test_off_parity_legacy_get`, OFF-гейты web/image/youtube/video — passed.
- `MCA_EGRESS_GUARD_ENABLED=false` → без egress-обвязки подпроцессов/yt-dlp: паритет-тесты — passed.
- Резолв per-call (`services/mca_gates.py:128–141`), `getattr`-default True, никогда не бросает; полный pytest 9678/0.

## Counterexamples checked

1. Redirect на private IPv4/IPv6/metadata — блок на каждой цели. ✔
2. Peer mismatch (rebinding) — блок; trusted IP-литерал — корректный peer-match. ✔
3. Большой stream — прерывание без полного чтения в RAM. ✔
4. gzip-бомба — `decompressed_too_large`. ✔
5. Metadata даже для trusted — безусловный блок. ✔
6. **Timeout SafeFetcher реально применяется** — ≤0.6 c при профиле 0.2 c (итер. 1: 1.52 c). ✔
7. OFF kill-switch = legacy. ✔
8. Частичный файл при ошибке выгрузки удаляется. ✔

## Adjudication residual-ов Builder (подтверждено итер. 2)

- **Cobalt egress вне процесса** — законное зарегистрированное ограничение (ADR-1027-5 D4; T7 Medium); отправляемый URL валидируется `guarded_target(..., trusted=True)`. Принимаю.
- **Live-проверка авторизованного видео — к релизу; `cleanup_deferred_dependency_unverified`** — законно (§6.2); cookies не удалены, `git ls-files` чист.
- **`_generate_get` legacy** — доверенный провайдер, не пользовательский URL; follow-up `mca-19`. Low-заметка сохраняется, не блок.
- **`unverifiable` peer при MockTransport** — extension `network_stream` в проде даёт httpx 0.28.1; `unverifiable` → WARN+продолжение, mismatch → блок. Зафиксировано в threat F8.

## Unavailable checks

- Live-проверка авторизованного видео-сценария (creds/аккаунт недоступны) — deferred to `mca-release` (законно).
- Реальный deploy — не выполнялся (`DEFERRED_TO_RELEASE`).

## Вывод

**Status: Approved** (B-MCA02-1 закрыт; M-MCA02-2/-3 и L-MCA02-4 закрыты; новых findings нет). Условие итер. 1 выполнено; binding итер. 2 зафиксирован Reviewer'ом. Разблокировано: **Merge §97** и `ADR-1027-5 → Accepted` (решение @Architect).
