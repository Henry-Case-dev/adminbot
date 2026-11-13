# S4 (stage D) - повторное ревью после исправлений B1/N1

- **Эпик:** SMART-EXECUTION-RELIABILITY-01, slice **S4-CAPACITY**.
- **Кандидат кода:** `f55fdc6e`; docs-коммит `8e48b8cc`; база `d20a7f73`.
- **Worktree:** `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\SMART-EXECUTION-RELIABILITY-01-92d1db8aefb1-7df1e82b` (ветка `smart/d-capacity`).
- **Привязка:** `git diff f55fdc6e..8e48b8cc -- services config tests` пуст; docs-коммит меняет только evidence. Предыдущее ревью: `review-d-1a991e7d.md`.
- **Контракт:** `architecture-contract-part2.md`, раздел D (S4); owner input `plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md`, ЭТАП D.
- **Требования карты:** `SXR-D1-01`, `SXR-D1-02`, `SXR-D1-03`, `SXR-D2-01`, `SXR-D2-02`, `SXR-D3-01`, `SXR-D3-02`, `SXR-D4-01`, `SXR-D5-01`, `SXR-D6-01`.
- **Вердикт:** **Approved (review-stage)**; все D-строки REVIEW-ready. Parent DONE не отмечать: живые production-проверки (каталог/effective values/реальный overflow) остаются postdeploy. Деплой не выполнялся.

## 1. B1 - исправлен

- `services/llm_client.py`: `LLMContextOverflowError(str(err))`; текст снова `LLM HTTP 400: <url>`. Тип, `status`, `body`, `model`, `base_url`, `context_info`, `context_recovery` сохранены.
- Новый тест `test_context_overflow_keeps_legacy_message_and_typing` идёт через реальный `_post`/`httpx.MockTransport` (400 + structured body): проверены текст, тип, `context_info.limit_tokens=32768`, `structured=True`, непустой `context_recovery`, записанный `proven_limit`.
- Прежний `test_final_400_logs_diagnostics` снова зелёный; `tests/test_llm_client.py` - **116 passed**.
- Независимый probe (отличающийся body/лимит: 65536, requested 71234): получены `LLMContextOverflowError`, текст `LLM HTTP 400: https://nano-gpt.com/api/v1/chat/completions`, `limit_tokens=65536`, `structured=True`, `plan_budget=56097`, `proven_limit=65536`. `INDEPENDENT_PROBE_OK`.

## 2. N1 - исправлен

- `services/model_capacity.py`: `_same_model_id` (lower/basename/без routing-суффикса) используется в `invalidate_runtime_capacity` (сравнение cache-key) и в очистке `_WINDOW_CACHE` внутри `record_proven_limit`.
- Новый тест `test_proven_limit_invalidates_full_id_cache_for_short_id`: cache под `z-ai/glm-5.3-flash-uncensored` + proven limit по короткому ID -> stale cache отсутствует, `resolve_capacity` возвращает `proven_limit 131072`; обратное направление (proven по полному ID виден короткому) тоже проверено.
- Независимый probe: full-ID cache 1048576 + short-ID proven 131072 -> `stale_cache=0`, `_WINDOW_CACHE` очищен, результат `proven_limit 131072`; после proven по полному ID короткое написание видит 65536. `N1_PROBE_OK`.
- Мутация: `_same_model_id` принудительно переведён на raw-сравнение -> новый N1-тест **failed** (`stale cache` остался); после restore - **passed**. Worktree чист.

## 3. Diff и scope

- Инкремент `1a991e7d..f55fdc6e`: 5 файлов - evidence-переименование, `services/llm_client.py` (7 строк), `services/model_capacity.py` (26 строк), `tests/test_capacity_stage_d_smart.py` (+31), `tests/test_llm_client.py` (+44).
- `config/settings.py` в этом инкременте не менялся; общий diff к базе по-прежнему содержит только `CHAT_UNKNOWN_MODEL_WINDOW` (1M) и комментарии. Бюджетные ключи `CHAT_CONTEXT_BUDGET_TOKENS`, `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`, `CHAT_BUDGET_RESERVE_RATIO` не тронуты.
- Новых DDL, таблиц, БД или отдельного store нет; `_PROVEN_LIMITS` остаётся process-local dict. Новых бюджетных/секционных квот нет.

## 4. Прогоны

| Набор | Результат |
|---|---|
| `tests/test_llm_client.py` | **116 passed** |
| `tests/test_capacity_stage_d_smart.py` | **35 passed** |
| capacity/context/evidence, 11 файлов | **281 passed** |
| D6/Writer/инспектор + Direct, 14 файлов | **476 passed** |
| прежний legacy-тест `test_final_400_logs_diagnostics` | **passed** (в составе 116) |
| мутация N1 raw-сравнение | **failed**, после restore **passed** |
| независимые probes B1/N1 | **OK** (см. выше) |

Широкий `-k "capacity or context"` (заявленные Builder'ом 961/3 pre-existing) в этом фокусном проходе не перезапускался; для изменённого контура прогнаны 116/35/281/476, покрывающие затронутые seams. RED на базе `d20a7f73` для исходных D-инвариантов остаётся в силе из `review-d-1a991e7d.md`; код с тех пор только исправлял B1/N1.

## 5. Acceptance ledger

| ID | Статус | Доказательство |
|---|---|---|
| SXR-D1-01 | VERIFIED | Заводское 1M и отсутствие 16384-fallback подтверждены ранее; base RED; код D1 в инкременте не менялся; 35/281 зелёные. |
| SXR-D1-02 | VERIFIED | `estimated_unknown`/`estimated`, marking в slots/analytics; без предзаполнения; 35/281. |
| SXR-D1-03 | VERIFIED | Точные registry-записи сохранены; family-префиксы не определяют ёмкость (требование D2/D3); `deepseek-v4.1-flash` - честная 1M-оценка до каталога. |
| SXR-D2-01 | VERIFIED | Единый resolver и все уровни (provider/base_url/route/exact ID/runtime/catalog/cache/override); 281/476. |
| SXR-D2-02 | VERIFIED | Precedence proven -> override -> runtime -> catalog -> cache -> exact registry -> 1M; conflict-поля; N1 закрыт тестом и probe. |
| SXR-D3-01 | VERIFIED | NanoGPT exact-ID через `_adapter_nanogpt_catalog`; namespace/suffix/alias; ambiguous basename = miss; 35. |
| SXR-D3-02 | VERIFIED | Выдуманной registry-записи нет; catalog miss -> 1M/registry; 35. |
| SXR-D4-01 | VERIFIED | Direct primary/fallback, tool/search/orchestrator/L1 используют фактическую модель; primary не занижается; 281/476. |
| SXR-D5-01 | VERIFIED | Бюджетные ключи не тронуты; окно/бюджет/max_output разделены; budgets OFF-тест в 281. |
| SXR-D6-01 | VERIFIED (review-stage) | B1 закрыт: реальный `_post` 400+structured body даёт typed overflow, legacy-текст, план и proven_limit; старый legacy-тест зелёный; recovery L2 покрыт 35/476. Живой provider-overflow остаётся postdeploy. |

**REVIEW-ready:** все строки `SXR-D1-01`, `D1-02`, `D1-03`, `D2-01`, `D2-02`, `D3-01`, `D3-02`, `D4-01`, `D5-01`, `D6-01`. Это review-stage доказательство, не production acceptance и не parent DONE.

## 6. Postdeploy / не проверено

- Живой каталог NanoGPT: реальные `context_length`/`max_output_tokens` для `z-ai/glm-5.3-flash-uncensored`, доступность `detailed=true`, смена модели.
- Production effective values: env/hot `CHAT_UNKNOWN_MODEL_WINDOW`, `CHAT_MODEL_CONTEXT_WINDOW`, `models.chat_context_window_override`, слоты, fallback model/base_url, kill-switch'и.
- Реальный context-overflow от провайдера: один recovery/recompose-цикл, сохранение tool evidence, отсутствие миллионного probe, события/метрики; `_PROVEN_LIMITS` сбрасывается рестартом (осознанное ограничение).
- L1 fallback для catalog-only маленькой модели (sync-путь) и реальный fallback-recompose.
- Эти пункты не блокируют review-stage approval, но обязательны для release/deployed acceptance; parent DONE не отмечать.

## 7. Handoff

- **Implementation:** проверены `_context_overflow_exc` (текст/тип/поля), `_same_model_id` и обе точки инвалидации, новые тесты и diff инкремента.
- **Test validity:** 116/35/281/476 зелёные; новый B1-тест идёт через реальный `_post`; новый N1-тест проверяет stale cache и оба направления; мутация raw-сравнения ловится.
- **Independent challenge:** 400+structured body с limit 65536 -> legacy-текст, typed error, plan 56097, proven 65536; full-ID cache + short-ID proven -> proven 131072; оба probe OK.
- Отчёт: этот файл. Worktree кандидата сохранён; временный run `probe-d8271b2181` закрыт; карта/scope не правились; эпик DONE не отмечался.
