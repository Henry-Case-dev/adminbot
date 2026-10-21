# Review CFG-07CG-TAIL — хвост 07C.1–.6 (guard outbound-швов + наблюдения + ресанкция пинов)

- **Вердикт: Needs Fixes** (1 блокер — телеметрия guard-шва; функциональная часть швов верна).
- **Ревьюер:** REV-CFG07CG-TAIL (read-only), 21.10.2026.
- **Кандидат:** `f1e31d27` поверх `7c3a1350` (волна словаря). Дифф подтверждён: 14 файлов —
  `services/public_speech_guard.py` (+guard_public_text/GuardResult/is_honest_limitation),
  `services/factcheck_orchestrator.py` (+_guard_outbound/_apply_delivery_guard, швы busy/no_claim/
  ambiguous/attribution_miss/error), `services/tool_router.py` (+_guard_tool_verdict, строго `if v2:`),
  tests ×6, evidence-доки ×5. W3-фриз цел (prompts/prompt_migrations вне диффа). Гигиена: файлов волны
  в грязном дереве НЕТ (только foreign asap8/samples-ux/owner/tools); секретов нет;
  w7-dispute-metrics.json — только latency 6→5. Ridealong (nonblocking): коммит несёт 4 docs
  cfg-07a (f1-custom-suppress, review-f1, review-07cg) — чистые доки, кода F1 в коммите нет.

## Блокер (1)

**B1 (Medium, блокер по букве скоупа): `stage_event("egress_guard", "flagged", ...)` никогда не
эмитит событие.** `"flagged"` ∉ `ALL_OUTCOMES` (mca_events: start/success/silent/skipped/failed/
cancelled/pending_external/interrupted) → `build_event` возвращает None → событие теряется всегда.
Runtime-доказательство на кандидате: `build_event("factcheck_temporal", outcome="flagged",
stage="egress_guard") -> None`; `outcome="failed"` → OK.
- Локации: `services/factcheck_orchestrator.py::_guard_outbound` и
  `services/tool_router.py::_guard_tool_verdict` (обе точки).
- Нарушенный пункт брифа: «FORBIDDEN/overclaim → срез + WARNING + **stage_event**» (п.1) —
  телеметрическая нога шва инертна; работает только logger.warning. Постдеплой-мониторинг guard'а
  (07C.6) по mca_events был бы невозможен.
- Доставку не рвёт (fail-open), юзер-видимого поведения не касается; тестов на stage_event нет —
  потому и не поймано.
- Минимальная правка: `"flagged"` → `"failed"` ×2 (WARN + terminal → durable-буфер; stage
  свободное поле, валидация проходит — проверено runtime). Findings в reason_code по R17
  отбрасываются (не канонические коды) — остаются в WARNING-логе, это норма.
- Минимальный речек: runtime-проба build_event + `test_cfg07_guard_tail.py` (26p) + grep
  отсутствия "flagged" в services/.

## Acceptance ledger (скоуп лейна)

| Пункт | Статус | Доказательство |
|---|---|---|
| Delivery-шов 07C.1/.4: guard после Writer/кеш-хита, до render; срез с границами слов, факты целы | VERIFIED | код + TestDeliverySeam (dirty→срез, honesty байт-в-байт, fail-soft); enum сохраняется при repair; вырожденный → заголовок реального enum + factual_verdict=None (renderer не задублирует) или LLMBadResponseError→honest пул (🗿); кеш пишет сырой verdict_text, guard идемпотентен |
| WARNING + stage_event на швах | **FAILED (B1)** | событие не эмитится никогда (outcome невалиден) |
| short_reply: LLM-реплика чистится; вырождение → CLARIFY-пул | VERIFIED | TestShortReplyAndPools (ambiguous guarded, fallback pool) |
| no_claim/attribution_miss/busy/search_error/llm_error/unexpected_error — guard перед reply | VERIFIED | код всех 6 швов + пулы байт-в-байт (test_canned_pools_pass_guard_byte_identical, 6 пулов) |
| tool_route v2: NL-verdict чистится, машинный JSON цел; вырожденный → failed БЕЗ записи прогона; строго `if v2:` | VERIFIED | TestToolRouteSeam; record_temporal_run ПОСЛЕ guard-returns (tool_router:2551); конверт (claim/reason/статусы) нетронут |
| OFF-паритет: spy → 0 вызовов guard, payload байт-в-байт | VERIFIED | test_off_parity_guard_not_applied + структурно: run_factcheck только за _pipeline_v2_enabled (handlers/factcheck.py:515), tool-ветка `if v2:` |
| Наблюдение 1: SpyAggregator реально инжектится, ассерт связан; privacy не ослаблена | VERIFIED | svc.aggregator=agg в test_attribution_miss...; усиление гарантии no-external-search |
| Наблюдение 3: is_honest_limitation + allow-путь; PC-01 не режется (unit + delivery байт-в-байт) | VERIFIED | test_honest_limitation_in_allow_path + test_honesty_class_verdict_byte_identical |
| Наблюдение 2: инверсный overclaim НЕ в словаре, осознанный остаток с источником | VERIFIED | 07cg-tail.md §2.2 (07A.7-обоснование, runtime-проверка); новых паттернов overclaim в диффе нет |
| Ресанкция ×4: 301→302, c849dbf4-месс | VERIFIED | `git show --stat c849dbf4`: 4 файла НЕ в коммите (только mca17c); REASON_CODES=302 runtime; 4 пина+mca17c+attribution green |
| Гейт: `--stage review --slice CFG-07A --candidate 211a8c1bdb99…` EXIT 1 ровно 5 | VERIFIED | EXIT 1, errors=5: 07A.3/.5, 07D.1/.2, 07A.F — PENDING (ledger-долг review-07cg, закрывается композитным гейтом оркестратора); (первый прогон с сокращённым SHA дал 18 ложных — артефакт моей команды, не карты) |

## Прогоны (независимые, на кандидате)

- `test_cfg07_guard_tail.py` + `test_cfg07_egress_dictionary.py` + `test_unified_core_route_coverage.py` = **111 passed** (26+67+18), EXIT 0.
- Фактчек-семья (orchestrator/attribution/renderer/tool_route/w6/planner/w7) + 4 ресанкционированных пина + mca17c_invariants = **193 passed**, EXIT 0.

## Incidental (nonblocking)

- Stale-комментарий `already_delivered`/«cache-hit ветка ответила сама» (orchestrator:135,529) противоречит поведению: cache-hit доставляется через общий поток (single delivery, guard применяется) — pre-existing CFG-06 W3, не регресс лейна. Поправить попутно при B1.
- `_apply_delivery_guard` импортирует приватный `_VERDICT_HEADLINE` renderer'а — допустимо (тот же пакет контракта), не блокер.

## До CFG-FINAL

1. Builder: фикс B1 (2 строки) + речек (проба + 26p) — коммит волны хвоста.
2. Оркестратор: композитный гейт всего эпика CFG (все слайсы), закрытие 5 PENDING-строк
   (07A.3/.5, 07D.1/.2, 07A.F) evidence-биндингами на фактические SHA, `--stage release` после деплоя
   + postdeploy-проверка 07C.6 (логи WARNING/stage_event egress_guard на проде).
3. Биндинг этого ревью: кандидат `f1e31d27`; любые изменения services/tests до фикса B1 инвалидируют
   соответствующие строки ledger.
