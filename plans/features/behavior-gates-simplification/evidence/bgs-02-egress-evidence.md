# BGS-02 — Evidence Egress Guard: наблюдение вместо постцензуры

- Lane: `BGS-02-EGRESS`, ветка `bgs/egress-guard`.
- База: `da6299e9` (BGS-01 уже в `evol/impl`).
- Кандидат: `69a0c6ae`.
- Источник: `plans/owner_inputs/2026-11-05-behavior-gates-simplification.md`,
  §3 BGS-02 (п.1–7), §9 приёмка (компонентные тесты, сценарий D), §8 матрица.
- План интеграции: `plans/features/behavior-gates-simplification/arch/bgs-integration-contract.md`
  §0.2, §3, §6 (S2), §7 (CRM), §9.

## Что изменено

| Файл | Строки | Изменение |
|---|---|---|
| `services/evidence_policy.py` | 926–931 | `GUARD_HINT_RETRY`/`GUARD_ONE_LOOKUP`/`GUARD_DROP_CLAIM` удалены; осталось `GUARD_NONE` + единственный код наблюдения `GUARD_OBSERVED_UNVERIFIED` |
| `services/evidence_policy.py` | 1083–1125 | `EgressVerdict` → `EgressObservation`: `observed`, `sentence_index`/`char_start`/`char_end`, `location`, `event_fields()`; права на удаление/повтор/lookup удалены |
| `services/evidence_policy.py` | 1143–1214 | `guard_egress` больше не возвращает приказ: одно наблюдение (код + место), текст не меняется; `drop_claim_sentence` удалена |
| `services/evidence_policy.py` | 174–180 | `REASON_EVIDENCE_CLAIM_OBSERVED` (новый активный код); `REASON_EVIDENCE_CLAIM_REMOVED` оставлен декодером старых строк |
| `services/mca_events.py` | 374–380 | `evidence_unverified_claim_observed` в `REASON_CODES`; `..._removed` помечен legacy (производителя нет) |
| `services/direct_chat_service.py` | 2696–2726 | `_run_evidence_egress_guard`: только наблюдение, возвращает ровно входной текст; параметры `lookup`/`rewrite`/`drop_allowed` удалены |
| `services/direct_chat_service.py` | 5312–5340 | Direct (после L2, до отправки): наблюдение + событие; `answer` не подменяется |
| `services/direct_chat_service.py` | 5353 | снято взаимоисключение с freshness-ретраем (`_evidence_retry_used_here` больше не существует) |
| `services/direct_chat_service.py` | 12981–12990 | Initiative: тот же postprocess, без lookup/повтора/удаления |
| `services/direct_chat_service.py` | 6429–6475 | `EVIDENCE_EGRESS_CHECK`: `observed`, `code`, `sentence_index`, `char_start`, `char_end`, `reason`, `note` (без текста, R17) |

Удалено целиком: `drop_claim_sentence`, `GUARD_DROP_CLAIM`/`GUARD_HINT_RETRY`/
`GUARD_ONE_LOOKUP`, `_evidence_lookup` (второй адресный поиск после Writer),
`_evidence_rewrite` + `EVIDENCE_EGRESS_HINT` (повторная генерация по эвристике).

Сохранено: проверка claim↔evidence по РЕАЛЬНО доставленной выдержке
(`_supported`, `delivered_claim_keys`, `claims_coverage`, `_content_ref`/
`source_ids` в пакете `direct_execution` — не трогались), классовый skip
(`GUARD_SKIP_CLASSES`), атрибутированная речь, «не ищи в интернете»
(`is_external_forbidden`), честные строки Writer'у (`_evidence_writer_note`:
«не утверждай, что проверил», «выдержек нет — не добавляй внешних фактов»),
RBAC/провайдер/квота/SSRF (`allowed()`), технические санитайзеры
(`outgoing_guard.sanitize_outgoing`, `TELEGRAM_SEND_GUARD_ENABLED`),
`mca_gates.egress_guard_enabled()` (loopback/media — другой механизм).

## Форма события

`EVIDENCE_EGRESS_CHECK` (agentic) и `evidence_egress_check` (MCA):

```
observed:      0|1
code:          "none" | "observed_unverified_claim"
sentence_index:0-based индекс предложения (-1 = нет)
char_start/end:0-based срез в готовом тексте (-1 = нет)
reason:        "" | "evidence_unverified_claim_observed"
note:          "unsupported_claim_observed" | "planned_claim_unobserved"
               | "not_externally_factual" | ""
claim_key:     цифры claim'а (для claim↔evidence телеметрии)
```

Текст ответа в событие не попадает (R17). Доставка = L2-оригинал ± техническая
санитаризация маркеров.

## Где удаление было «несущим» для честности

Единственная точка, где удаление влияло на решение о доставке, — ветка
`if not answer: … react_moai()` в Direct: удалённое предложение могло превратить
ответ в пустой и заменить его реакцией. Теперь guard не может обнулить текст, а
честность обеспечивается ДО генерации (evidence-пакет, статус проверки и
инструкции Writer'у) и наблюдаемостью (событие), а не вырезанием мысли.
Отдельной «проверено»-метки или ссылки вне фактчека пайплайн не добавляет —
это проверено тестом (`test_direct_handle_unverified_claim_not_labelled_verified`).

## Тесты

Новый контрактный файл: `tests/test_bgs02_egress_observation.py` (10 тестов):
ранее удалявшийся claim доставляется байт-в-байт; события несут код+место и не
несут текст; на реальном `handle()` один Writer-вызов и доставка == L2; честная
пометка едет до генерации; `<thought>`/`fact:ID` по-прежнему вычищаются; RBAC/
SSRF/квота/рубильник сохраняют свои коды; `mca_gates` не задет.

Переписаны под новый контракт: `tests/test_evol_evidence_routing.py`,
`tests/test_evol_evidence_corpus.py`, `tests/test_evol_w17_small_canon_reqs.py`,
`tests/test_evol_reply_context_consumers.py` (проверка «повтор guard'а идёт по
той же репрезентации» заменена на «повтора нет: один Writer и один манифест»).

Прогоны (кандидат `69a0c6ae`):
- `tests/test_bgs02_egress_observation.py` + 4 переписанных файла → **194 passed**.
- `tests/test_evol_evidence_*.py tests/test_direct_chat*.py` + новый файл → **494 passed**.
- Мутация (возврат удаления в двух половинах: guard вырезает + call-site
  доставляет мутированный текст) → **12 failed** в этих же файлах; после отката
  снова зелено.

Известные падения (проверены на базе `da6299e9`, к BGS-02 не относятся):
`tests/test_history_w4_fixes.py` (баннер/границы окна — 8 тестов),
`tests/test_er65_sent_segment_snapshot.py` (байт-стабильный снапшот сегмента),
`tests/test_outgoing_guard_round1022.py::TestSendPointsCoverage` (реестр
SEND_POINTS). «projection» и «aggregator taxonomy» в этом дереве зелёные.

## Что НЕ доказано этим срезом

- Живой прогон с реальным Web Search/L2/Telegram не выполнялся (только
  детерминированные швы); сценарий D §9 требует preprod-прогона.
- Показ события в Inspector (BGS-02.9 «точное соответствие готового текста и
  доставки») — backend-контракт готов, UI-часть принадлежит UR-F/PVR-UI
  (BGS-06 BLOCKED_BY), в этом срезе не реализуется.
- `BGS-ANC-03` относится к снятию privacy-вызова в `_evidence_context` и уже
  выполнен влитым BGS-01 (`ur/b-search`); здесь не менялся.
- `BGS-02.5`/`BGS-02.11` (структура фактчека, тестостерон-картинка) не
  затрагивались: фактчековая доказательная связь не менялась.
