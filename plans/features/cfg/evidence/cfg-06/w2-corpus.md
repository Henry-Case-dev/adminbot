# CFG-06 W2 — регресс-корпус suitability gate (06J.5)

- Gate: `fsg1`, протокол двух проходов (needs_context → одно ограниченное расширение).
- Фикстуры: 20 / 100 / 200 / 500 сообщений; кейсы а–з + негативы (е2 мат+тезис, е3 сарказм).

## Метрики

| Метрика | Значение |
|---|---|
| cases_total | 40 |
| routing_accuracy | 1.0 |
| false_refusal_rate | 0.0 |
| false_contextual_claim_rate | 0.0 |
| unnecessary_search_rate | 0.0 |
| target_attribution_errors | 0 |
| relevant_context_recall | 1.0 |

## Расхождения

Нет: все кейсы на всех фиксурах совпали с ожиданием.

## Заметные маршруты

- а: checkable_in_context / checkable_factual_claim / scope=web / conf=0.8 / items=1
- б: checkable_in_context / checkable_factual_claim / scope=web_and_chat / conf=0.61 / items=1, author=Вася
- в: checkable_in_context / checkable_factual_claim / scope=web_and_chat / conf=0.6 / items=1, author=Петя
- г: ambiguous_needs_clarification / question_without_assertion / scope=chat_history / conf=0.35 / items=0
- д: checkable_in_context / checkable_factual_claim / scope=web_and_chat / conf=0.61 / items=1, author=Вася
- е: no_claim_after_context / nonsense_semantically_incoherent / scope=none / conf=0.7 / items=0
- е2: checkable_in_context / checkable_factual_claim / scope=web / conf=0.8 / items=1
- е3: checkable_in_context / checkable_factual_claim / scope=web / conf=0.8 / items=1
- ж: checkable_in_context / checkable_factual_claim / scope=web / conf=0.8 / items=1, temporal_hint
- з: context_unavailable / unsafe_or_unavailable_target / scope=none / conf=0.9 / items=0
