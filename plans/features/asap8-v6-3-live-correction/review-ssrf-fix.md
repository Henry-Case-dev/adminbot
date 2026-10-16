# Review — FIX-SSRF guard-order (web_content_extractor) — независимый adversarial-ревью

Candidate: worktree (uncommitted), HEAD `31c165556dbe8c289606bd6bee1af49bb72d5794`
Дата: 2026-10-16. Интерпретатор: `.venv\Scripts\python.exe` (canonical).

## Точная привязка кандидата

- `services/web_content_extractor.py`: HEAD blob `380d25cf3fdc0c4383b9341b92266713c8fd360c` → worktree sha256 `D4DDCD0B752EE68469626B41CE332B9B04A803CAC78347FB63678E43F88E4218` (совпадает с заявкой). `git diff`: ровно 1 hunk `@@ -143,11 +143,23 @@`, +15/−3.
- `tests/test_soul13_ssrf_guard_order.py`: новый (untracked), `TEST-LIFECYCLE: REGRESSION owner=SOUL-13/SSRF-guard`.
- Не изменены vs HEAD (проверено): `services/safe_fetch.py`, `services/mca_gates.py`, `config/settings.py`, `services/hot_config.py`.
- Общий worktree содержит правки других лейнов (prompt_registry/prompt_migrations/direct_chat_service… 21:43–21:57) — к scope FIX-SSRF не относятся.

## Falsifiability (собственный прогон)

- Новый файл на текущем кандидате: **10 passed** (3.7 s).
- Pre-change blob (`380d25cf`, byte-exact, `git hash-object` совпал) подгружен в scratch через sys.modules-инъекцию (repo не менялся): **5 failed, 5 passed**. Провалены: 4× `dangerous_destination...[missing]` + `test_guard_consulted_before_local_extraction_unavailable`. Прошли: 4× `[installed]` + OFF-legacy. Совпадает с заявкой лейна.
- Регрессионный фон: `tests/test_web_content_extractor.py` + `tests/test_mca02_safe_fetch_round1027.py` → **88 passed**.

## Acceptance ledger

| Пункт | Статус | Доказательство |
|---|---|---|
| Гард читается до проверки trafilatura | VERIFIED | diff hunk; тесты 10/10 |
| Опасный литтерал (private/metadata/file/credentials) не уходит в облако без trafilatura | VERIFIED | 4 missing-теста на реальном `aguarded_target` (без DNS — все блокировки до резолва) |
| OFF-паритет | VERIFIED | каноническая ветка текст. не изменена; добавлен только чистый `getattr`-read (ClassVar bool, без side effects); OFF-тесты зелёные на old и new |
| Pre-flight — реальная проверка, не no-op | VERIFIED | прогон `guarded_target(trusted=False)`: `10.0.0.1`→destination_blocked(private), `169.254.169.254`→metadata_endpoint_blocked, `file://`→scheme_not_allowed, creds-URL→credentials_in_url, `localhost`→destination_blocked(loopback, через resolve), `metadata.google.internal`→metadata_endpoint_blocked; `example.com`→резолв в реальные IP; `.invalid`→resolve_failed |
| Нет новых утечек в логи/ошибки | VERIFIED | сообщения `SafeFetchError` без URL; policy-ветка маскирует URL через `mask_url` (R17); pre-flight ничего не логирует |
| Scope-дисциплина лейна | VERIFIED | только 2 файла; sha256/mtime совпадают с заявкой |

## False-positive / latency

- Новых ложных блокировок сверх канонического ON-режима нет: блокируются только цели, которые канонический SafeFetcher блокирует и так (private/loopback/metadata/scheme/credentials). Легитимный локальный путь (trafilatura installed) не затронут.
- В degraded-режиме (trafilatura нет) добавлен один DNS-резолв в executor; вызывающий `fetch_article` уже ограничен `asyncio.wait_for(_ARTICLE_TOOL_TIMEOUT)` — зависания нет.
- Принятая цена: сервер теперь делает DNS-запрос к пользовательскому hostname до облачного фолбэка (инфо-канал на resolver) — та же модель, что и в каноническом ON-режиме.

## ADJACENT GAP — `resolve_failed` вне `_POLICY_BLOCK_CODES`

Вердикт: **реальный, но узкий gap; pre-existing; одинаков в обоих ON-режимах; не блокирует этот релиз; запланировать с явным решением owner.**

- Факт: `services/web_content_extractor.py:38-42` не содержит `resolve_failed` → URL с hostname, не резолвящимся локально, уходит в Tavily/Exa без проверки адресов. Литтеральные проверки при этом уже применены; канонический ON и degraded-ON ведут себя идентично; HEAD blob содержит тот же набор кодов (не внесено этим лейном).
- `client_error`/`safe_fetch_timeout` — НЕ добавлять: возникают после успешной destination-валидации (`_request` валидирует до connect); это не validation-gap, а транзиенты, где фолбэк уместен. `too_many_bytes`/`decompressed_too_large` — тоже post-validation.
- Минимальное изменение: добавить `"resolve_failed"` в `_POLICY_BLOCK_CODES` (1 токен) + точечный тест.
- Blast radius на канонический путь: при транзиентном сбое локального DNS статья больше не спасается облачным фолбэком → пользователь получает жёсткую ошибку. Соседний прецедент `tools/video_downloader.py:386` сознательно НЕ блокирует `resolve_failed` («транзиентный DNS-сбой не блокируем ложно»), но там фактическая загрузка остаётся под локальными контролями (egress-guard), тогда как облачная переадресация — нет. Это tradeoff security/availability → решение уровня owner/Architect, не побочный эффект регресс-фикса.
- Рекомендация по релизу: не блокировать guard-order-фикс; завести отдельный follow-up: либо блок (`resolve_failed` в policy-код, принять потерю фолбэка), либо bounded retry перед fallback, либо явно принять риск с обоснованием. До решения не публиковать формулировки «опасные назначения никогда не уходят в облако» без оговорки.

## Вердикт

`Verdict: Approved` — для guard-order изменения самого по себе. Adjacent gap — schedule (non-blocking), с обязательной записью владельца.
