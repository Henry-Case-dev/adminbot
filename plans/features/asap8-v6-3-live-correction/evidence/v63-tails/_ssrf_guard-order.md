# FIX-SSRF — порядок safe-fetch-гарда не зависит от trafilatura (SOUL-13/SSRF-guard)

Лейн: `FIX-SSRF` (writer, без деплоя/SSH/коммита/Telegram). Инцидент найден лейном
v6.3-tails (см. раздел Incidental в `v63-tails-report.md`).

## Дефект (before)

`services/web_content_extractor.py` (HEAD, sha256 `380d25cf…` blob):

| Строка | Код |
|---|---|
| 147-148 | `if trafilatura is None:  # pragma: no cover` → `raise RuntimeError(...)` |
| 150 | `if mca_gates.safe_fetch_enabled():` — гард назначения (SafeFetcher) **после** проверки пакета |

Без трафилатуры уровень-1 падал `RuntimeError` (обычный `Exception` → «level failed →
fallback»), и опасный URL уходил в облачные фолбеки Tavily/Exa. Инвариант «опасное
назначение не уходит в облако» держался только при установленном пакете; в канонической
среде (trafilatura 2.2.0) баг был замаскирован.

## Фикс (after, sha256 файла `d4ddcd0b…`)

| Строка | Код |
|---|---|
| 153 | `safe_fetch_on = mca_gates.safe_fetch_enabled()` — гард читается **первым** |
| 154-158 | `if trafilatura is None:` → при включённом гарде `await safe_fetch.aguarded_target(target_url, trusted=False)` (pre-flight: normalize/credentials/SSRF-адреса, БЕЗ загрузки страницы) |
| 160 | `raise RuntimeError("trafilatura is not installed")` (только после проверки назначения) |
| 162 | `if safe_fetch_on:` — ветка SafeFetcher, семантика прежняя |

15 insertions / 3 deletions; `# pragma: no cover` снят (ветка теперь покрыта тестом).
`aguarded_target` — тот же самый вызов, который `SafeFetcher.fetch` делает первым
(`safe_fetch.py:532`), поэтому коды policy-блокировки совпадают. Нормальный путь
(trafilatura есть) не изменён: ни лишнего DNS-резолва, ни лишнего запроса.

## Регресс-тест

`tests/test_soul13_ssrf_guard_order.py` (sha256 `23f182ad…`, new) —
`TEST-LIFECYCLE: REGRESSION owner=SOUL-13/SSRF-guard`; наличие пакета переключается
швом модуля (`services.web_content_extractor.trafilatura = None`), пакеты не удаляются.

## Доказательства (команды и результат)

1. **Repro до фикса** (venv, шов `trafilatura=None`, назначение `http://10.0.0.1/private`):
   `cloud fallback calls = [('tavily', 'http://10.0.0.1/private'), ('exa', 'http://10.0.0.1/private')]`,
   `safe_error = None`, `INVARIANT VIOLATED`. Скрипт: `OPENCODE_WORKFLOW_SCRATCH/ssrf-fix/repro_order.py`.
   После фикса тот же скрипт: `destination blocked | code=destination_blocked`,
   `cloud fallback calls = []`, `invariant held`.
2. **Фальсификация теста** (порядок временно возвращён в исходный, `git diff` пуст):
   `pytest tests/test_soul13_ssrf_guard_order.py -q` → **5 failed, 5 passed**
   (краснеют все 4 строки «missing + опасный URL» и seam-тест порядка; строки
   «installed» и OFF-паритет зелёные). После восстановления фикса — 10 passed
   (sha256 модуля снова `d4ddcd0b…`).
3. **Маскировка в каноне / RED без пакета** — один и тот же node id
   `test_mca02_safe_fetch_round1027.py::TestOffParityAndTrusted::test_web_extractor_blocks_destination_without_fallback`:
   - старый порядок: `.venv` (trafilatura 2.2.0) → **1 passed**; `py -3`
     (`import trafilatura` → `ImportError: lxml.html.clean…`, т.е. модуль = None) → **1 failed**;
   - новый порядок: `py -3 -m pytest "<тот node id>" tests/test_soul13_ssrf_guard_order.py -q`
     → **11 passed**.
4. **Focused (venv, `.venv\Scripts\python.exe`)**, новый порядок:
   `tests/test_soul13_ssrf_guard_order.py tests/test_web_content_extractor.py
   tests/test_mca02_safe_fetch_round1027.py tests/test_tool_chains_round1026.py::TestFetchArticle
   tests/test_tool_chains_round1026.py::TestR17AndBoundaries tests/test_web_summarizer_service.py
   tests/test_web_handlers.py tests/test_mca11_tool_result_round1028.py -q`
   → **189 passed** (10 новых + 179 существующих; вызов модуля — `services/tool_router.py:1528`
   `fetch_article` → `extractor.extract`, сервис `web_summarizer_service`).

Полная матрица (пины/команды) — `_ssrf_pytest_matrix.json`.

## Что ещё замечено в той же функции (не чинил — вне задачи)

- `resolve_failed`/`client_error`/`safe_fetch_timeout` не входят в `_POLICY_BLOCK_CODES`
  (`web_content_extractor.py:38-42`), поэтому URL, который локально не разрешился,
  уходит в облачные фолбеки **без валидации назначения**. Поведение одинаково и с
  трафилатурой, и без неё (pre-existing, к порядку гарда не относится), но именно оно
  остаётся единственным путём «непроверенный URL → облако» после этого фикса; решение —
  за Архитектором (ужесточение `_POLICY_BLOCK_CODES` изменит и канонический путь).
- На пути без трафилатуры pre-flight резолвит DNS публичных хостов (только там; в
  каноническом пути дополнительного резолва нет) — цена корректности инварианта.
