# CFG-07B-V — консолидация доказательств поглощения CFG-07B кандидатом UNIFIED-CORE

Лейн: CFG-07B-V (read-only над кодом; запись только сюда).
Дата: 20.10.2026.
Кандидат: **`1b23d4c9beb1544169f51781c2c8a45e8797f719`** (v2 = UNIFIED-CORE `37097f7c` + R1-fix, REL-25898).
Рабочее дерево: HEAD == кандидат; изменены только plans/доки — код дерева идентичен кандидату (все якоря читались из рабочего дерева и выборочно из `git show 1b23d4c9`).

## Итог

| Вердикт | Строк | Строки |
|---|---|---|
| REUSED | 9 | 07B.1–07B.8, ADD-1.C4 |
| REUSED (офлайн) + live → владельцу (не блокер) | 1 | 07D.3 |
| PARTIAL | 1 | 07D.4 |
| OPEN | 0 | — |

**CFG-07B поглощён кандидатом v2 полностью; новых реализаций не требует.** Таблица REUSED из `plans/features/cfg/cfg-07-build-plan.md` §2 подтверждена построчно: каждая строка сверена «файл:якорь → тест → статус прогона» и сопоставлена с исходным требованием `source-cfg-addendum.md` (L354–L361, L378–L379) и строками карты (L00033, L00354–L00361, L00378, L00379 — все ещё `PENDING`, закрытие строк — действие оркестратора/PM после G0).

Машиночитаемая сводка: `summary.json` (sha256 `0c4b81d594976782fb23b1b06e2ecc32e41afb7048aefa67f00644cfa011c9a3`).

## Независимый фокусированный прогон (на кандидате)

```
py -3 -m pytest tests/test_unified_core_route_coverage.py tests/test_add_exp_expression.py -q
→ 54 passed, 0 failed (3.93s)
```

- `test_unified_core_route_coverage.py` — collected ровно **18** (как в плане: factcheck two-call/single/byte-parity, summary narrator/single, checkup chat/tool-neutral, search, youtube, web, off-mode, hot-apply, factory defaults, fallback, миграционная лестница).
- `test_add_exp_expression.py` — collected **36** (в плане/брифе «30»; расхождение вверх — параметризация, покрытие больше заявленного).
- Ключевая подвыборка (`-k "factory_defaults or byte_parity_with_expression_off or owner_exact_texts or migration_read_alias or route or off_mode or hot_apply or diag_classes or no_profanity_postprocessor"`) — **23 passed / 0 failed**: этим самостоятельно покрыты ≥3 обязательных ключевых теста брифа (`test_factory_defaults_inject_core_and_occasional`, `test_owner_exact_texts_are_canon`, `test_migration_read_alias_keeps_data_and_never_frequent`) плюс route/off/hot/diag/postprocessor-семейство.
- Кросс-сверка с `fix-r1.md`: тот же фокусированный набор там — 328 passed; полный pytest — 12f/14632p/7err = parity с базой `99f5672c` (все failures pre-existing/env, атрибутированы). Противоречий нет.

## Ключевые подтверждения (выборка; полные — в summary.json)

- **8 call-sites `speech_owner_block`** — точно по плану: `factcheck_service.py:214,271`, `summary_generator.py:1850,4070`, `checkup_service.py:67`, `search_service.py:91`, `web_summarizer_service.py:71`, `youtube_summarizer_service.py:109,152,194`; определение `prompt_composer.py:740`. (Указатель из fix-r1 `checkup_service:59→71` — про `CHECKUP_FALLBACK_NOTICE`, не про этот якорь.)
- **Тексты владельца F3 байт-в-байт**: `mca_expression.py:72–83` (`PROFANITY_INSTRUCTIONS`), header `:112–122` («дословные цитаты и чужой текст передаются как есть»).
- **Режимы/factory/hot/merge**: closed set + read-alias `allowed`→`occasional` (`:36`, `:184–188`, `:250–256`, потребитель `speech.py:818`); factory ON = `occasional` (`:49–51`); `runtime_wired: True` (`speech.py:877`); effect-тексты F3 в `EXPRESSION_CONTROLS` (`speech.py:120–140`).
- **`MAT_ENABLED`/`SWEAR_ENABLED`** — `git grep` по кандидату: **0 совпадений**.
- **Диагностика**: `EXPRESSION_DIAG_CLASSES` (`:144–147`, 6 классов, R17-dedup, без приватных текстов) + `emit_expression_diag` (`:449`).
- **16 payload-трасс** `plans/features/add-exp/evidence/unified-core/trace-*.txt` — на месте; офлайн-артефакты `directives-fix/` (eval.json, red/green-exact, disjoint-check, budget, harness/eval_directives.py) — на месте; `owner_live_checks.md` §2 (live-набор 07D.3) — на месте.

## Что остаётся (не блокеры, адресаты известны)

1. **07D.4 → PARTIAL**: консолидированного спан-прогона URL/код/JSON/научные термины/числа/HTML против стилизации нет. Существующая защита: style policy сохраняет мат (`:413–427`), byte-parity OFF, tool-loop neutral, машинный план без expression. Остаток естественно закрывается acceptance **07C-G** («факты/ссылки/имена/цитаты/числа не меняет»). Новый тест в 07B-V не заводился (скоуп лейна — evidence-only).
2. **07B.7 → AGENT_CHECK**: измерение соблюдения/bounded retry — решение по офлайн-eval, только при систематической стерильности; механические счётчики отменены владельцем 20.10 — не возвращать.
3. **07A-2**: стык P0-заголовка Expression и жанровых исключений фактчека (план §6.7).
4. **Live владельцу** (опционально, не блокер): 07D.3 live-набор — `owner_live_checks.md` §2.

## Observations (без действий, для честности)

- `directives-fix/README.md` содержит исторический (база `19a235ea`, pre-UNIFIED-CORE) текст `EXPRESSION_HEADER` — зафиксированное evidence F3-фикса, не дрейф кода; текущий канон закреплён `test_owner_exact_texts_are_canon` / `test_design_canonical_strings_match_module`.
- Фактический путь управления: «Речь и характер» → раздел «Выражение» (`speech.py:1817`); формулировка `owner_live_checks.md` §2 («Речь» → «Как выражаться») — та же точка; оговорка размещения плана §6.1 закрыта позднейшим решением владельца (F3, 20.10).

TEST-LIFECYCLE: evidence-only lane; новые тесты не заводились (запрещено брифом).
