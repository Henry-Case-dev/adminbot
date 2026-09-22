# review.md — S1 `summary-filter-round1026` (T-3152, Step 5 @Reviewer)

> **Feature-ID:** `summary-filter-round1026` (Эпик 2, S1)
> **Status:** **Approved** (итерация 2)
> **Дата:** 23.09.2026 · **Ревьюер:** @Reviewer · **Базис:** рабочее дерево поверх `01f3c57` (tag `pre-round1026-s1` → `01f3c57`, `stash@{0}` сохранён)
> **Итерация 1:** Changes requested (B-1, M-1). **Итерация 2:** блокеры закрыты (ADR-1026-2, T-3160, L-R1026S1-1/-2).

## 1. Checks performed (воспроизведено независимо, итерация 2)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest (`.venv`, Py 3.12.0) | `.venv\Scripts\python.exe -m pytest -q` | **8501 passed / 0 failed / 1 warning** (107.24s), exit 0 ✅ |
| Интеграционный регресс | `pytest tests/test_summary_filter_integration.py` | **7 passed** ✅ |
| Модуль-матрица | `pytest tests/test_summary_filter.py` | **31 passed** ✅ |
| F8 / каталог / IA | `pytest test_round1025_f8_registry test_param_catalog test_ia_inventory_round1025` | **29 / 41 passed** ✅ |
| JS / синтаксис | `node --check web/app.js`; `node tests/js/*.js` | OK; **42/42** ✅ |
| `git diff --check` | — | exit 0 ✅ |
| Каталог (импорт) | REGISTRY/GROUPS/TAB_RULES/`_TAB_BY_GROUP`/Settings/categorized | **467/100/21/98/426/442** ✅ (санкция ADR-1026-1 D1) |
| Δ DDL | `git diff` по `database.py`/`pg_db.py`/`summary_memory.py` | пусто (`user_version=12`) ✅ |
| Публикация/промпты/XML | `git diff` по `image_generation.py`/`telegram_send.py`/`routes.py`/`summary_prompts.py`/`summary_xml.py` | пусто ✅ |
| F8-артефакты | sha256 `param_catalog.py` = фикстура; `--check` генератора | **match True**; `CHECK OK` exit 0 ✅ |
| Per-chat резолвинг (независимо) | `_resolve_from_root({'overrides':{flag:False}}, flag, True)` | **False**; `True`→True; `"false"`→False ✅ |
| Sentinel токенов | `resolve_context_tokens(0/None/-1/5000, 30000)` | 30000/30000/32000/5000 ✅ |

## 2. Находки → статус

| # | Sev (итер.1) | Статус | Доказательство закрытия |
|---|---|---|---|
| B-1 | High (governance) | **CLOSED** | `adr-1026-2-frozen-artifacts-reissue-amend.md` (Accepted, AMEND ADR-1025-21 D6) + `plans/ARCHITECTURE.md §67.6`. Артефакты F8 корректны: counts 467/100/98/21, delta 56, `superseded_by`, `app_version` исторический 2.58.15, sha256-пин совпадает, `--check` идемпотентен. Байтфризы `pg_db.py`/`routes.py` не тронуты, ассерты F8 — строгое равенство (не ослаблены). Откат не нужен. |
| M-1 | Medium | **CLOSED** | `summary_generator.py:335-346` — мастер-тумблер через `bool(await _chat_limit(chat_id, "flags.summary_filter_enabled", …))`; независимо подтверждён per-chat резолвинг (override False/True, строка "false"). Регресс `TestPerChatToggle`: `applied==[A,C]`, чат B OFF — фильтр не вызывается. |
| L-1 / L-R1026S1-2 | Low | **CLOSED** | `tests/test_summary_filter_integration.py`: OFF → `xml.build` получает тот же объект `memory.rows`; ON → XML=[1], RAG/graph=[1,2]; fail-open (`FILTER_ERROR`, Саммари доставлено); ON → ровно 2 LLM-вызова. |
| L-R1026S1-1 | Low | **CLOSED** | `resolve_context_tokens(…, 30000)` перед бюджетом §93 (0/None→дефолт, -1→32000); тесты `TestTokenCeilingNormalised` (0→limit 30000 fits True; -1→32000). |
| L-2 | Low | Open (debt) | `dropped`/`fragments` не сохраняются в `_filter_metrics` — S2/S3 переиспользуют `filter_window`. Не блокер. |
| L-3 | Low | Open (debt) | Явный дедуп по `id` — no-op при уникальных DB-id. Информационно. |
| L-4 | Low | Open (debt) | Косметическая правка отступа строки `SUMMARY_MAX_CONTEXT_CHARS`. Информационно. |
| T-3151 | — | Known gap | Браузерный UI/E2E не выполнен (нет стенда). Live/публикация — PENDING OWNER VERIFICATION (D4). |

**Новых находок итерации 2 — нет.** Введённый `resolve_context_tokens`/`_SUMMARY_CONTEXT_TOKEN_DEFAULT` согласован с `resolve_chat_limit(..., 30000, ...)`; char-потолок не вырождается, т.к. токен-потолок всегда >0.

## 3. Инварианты (подтверждено)

1. Δ DDL=0 (SQLite v12). 2. Δ каталога = санкция ADR-1026-1 D1 (ровно +8/+2). 3. D4-гейт: публикация/промпты/XML вне diff; ровно 2 LLM-вызова (тест). 4. CSP/zero-build, R17/R18 (логи — только числа/коды/id). 5. `APP_VERSION` 2.58.18 синхронен с README. 6. Маркер-тесты F8 строгие, не ослаблены. 7. F0/F4/F5/F6/F7/F9/F11 зелёные (полный pytest).

## 4. Unavailable checks

Браузерный E2E/Playwright, живой per-chat override, live-публикация — вне окружения; **PENDING OWNER VERIFICATION (D4)**.

## Handoff
**RESULT: Approved — `summary-filter-round1026` @Orchestrator** — B-1 закрыт санкцией ADR-1026-2 (F8 переиздан, байтфризы/ассерты строгие, откат не нужен); M-1 закрыт per-chat резолвингом + регрессом; L-1/L-R1026S1-1/-2 закрыты интеграционным регрессом и нормализацией токенов. Воспроизведено: pytest **8501/0**, JS **42/42**, `git diff --check` 0, каталог **467/100/21/98/426/442**, Δ DDL=0, публикация/промпты вне diff. Остаточный debt L-2/L-3/L-4 — не блокеры; T-3151 и live — на приёмке (PENDING OWNER VERIFICATION, D4). Дальше: @Scanner (T-3153) / merge @Architect (T-3155). Evidence: `plans/archive/summary-filter-round1026/review.md`.
