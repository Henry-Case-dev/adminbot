# CFG-07CG — единый egress-словарь honesty-классов (волна CFG-07C-G)

- **Лейн:** CFG-07CG (финальная содержательная волна 07C-G: словарь + positive-классы + тест-гарды).
- **Дата:** 21.10.2026. **Коммитов нет** (по брифу) — кандидат в рабочем дереве; биндинг
  `candidate_commit` выполняет оркестратор после коммита (прецедент 07A-2, `07a2-summary.md` §6.1).
- **Модуль-словарь:** `services/public_speech_guard.py` (новый; основа будущего guard'а 07C.1–.6 —
  интеграция на delivery-швах остаётся отдельной волной 07C-G-хвоста).
- **Гарды:** `tests/test_cfg07_egress_dictionary.py` — 67 тестов, `CONTRACT owner=CFG-07CG`.
- **Ограничения брифа соблюдены:** фактчек-каноны не тронуты (W3-фриз CFG-06 цел —
  `factcheck_prompts.py`/`prompt_migrations.py` вне диффа), 0 доп. LLM, 0 live-отправок, git не тронут.

## 1. Honesty-классы (единый источник; пулы — живые ссылки, НЕ копии)

| Класс | Условие допустимости | Источники (файл:пул) | Фраз |
|---|---|---|---|
| `honest_limitation` — честное ограничение | работа выполнена, но результата/ссылок недостаточно; сообщить можно и нужно (07A.3) | `factcheck_renderer._NO_LINKS_NOTICE`, заголовок `insufficient_evidence` («Недостаточно данных для проверки»); примеры PC-01 «проверил — не нашёл подтверждений», PC-09 | 2 (+3 примера) |
| `honest_refusal` — честный отказ | проверка РЕАЛЬНО состоялась (контекст изучен, история перечитана) — «не нашёл» допустимо, домыслы нет | `smartmodule_phrases`: FACTCHECK_NO_CLAIM (W2, после изучения контекста), FACTCHECK_CLARIFY, FACTCHECK_ATTRIBUTION_MISS (06G.3), FACTCHECK_EMPTY_CONTEXT, SEARCH_EMPTY_QUERY, CHAT_MEMORY_FORGOT_NONE, CHAT_MEMORY_CMD_DENIED, VIDEO_MEDIA_EMPTY, VIDEO_NO_SPEECH; примеры PC-02 «такого сообщения не нашлось» | 31 (+2) |
| `honest_unavailability` — честная недоступность | источник/сервис/LLM не ответили — говорим о недоступности, НЕ выдаём вердикт (07D.2); владельческий жанр пулов сохранён (PC-05/06) | SEARCH_ERROR (5.4), FACTCHECK_ERROR (5.4b), LLM_ERROR (5.5), YOUTUBE_ERROR (5.6), YOUTUBE_AGE_RESTRICTED (F16), WEB_ERROR (5.7), VIDEO_MEDIA_UNAVAILABLE/PROVIDER_TIMEOUT (5.11/5.11a), CHECKUP_FALLBACK/DEAD/LLM_ERROR (R42), CHAT_ERROR/LLM_DOWN/LOCK_BUSY (Ep.50/53/60), SMARTMODULE_BUSY (T-839), CHAT_COOLDOWN (58.2), THROTTLE (5.1), `checkup_prompts.CHECKUP_FALLBACK_NOTICE` (честный факт фолбэка, FA-08/D2) | 71 |
| `confirmed` — подтверждённый вердикт | ТОЛЬКО по реальному прогону: enum `CheckedVerdict.factual_verdict` + EvidenceMap; renderer не выдумывает заголовок без вердикта (W5); «нашёл подтверждение» после реального поиска — валидно (L377) | `factcheck_renderer._VERDICT_HEADLINE`: «Подтверждается»/«Не подтверждается»/«Подтверждается частично» | 3 (+1) |

Итого: 107 фраз из 29 живых пулов/констант + 6 канонических примеров владельца. Идентичность объектов
пулов закреплена тестом `test_honesty_classes_reference_live_pools` (правка пула автоматически
попадает в класс — второго источника истины нет).

## 2. FORBIDDEN-словарь метаречи (закрытые семьи; 14 семей / 42 маркера)

Источник-протокол: корпус `07a1-corpus.json` (MB-01…09/13…17) + аддендум L342/L345/L376/L377.
Покрытие корпуса закреплено тестом `test_corpus_metatext_families_covered` (каждая фраза и альт).

| Семья | Маркеры (голова + альты) |
|---|---|
| логи-самопрезентация (MB-01) | «по моим логам», «в моих логах», «в логах видно» |
| справка-источник (MB-02) | «в моей справке», «справка говорит» |
| вымышленный аналитик (MB-03) | «аналитик подтянул», «аналитик считает», «анализатор показал» |
| режиссура разбора (MB-04) | «разбор подъехал», «разбор готов» |
| декларация шутки (MB-05, 07D.1) | «сейчас сделаю смешно», «сейчас будет смешно», «сейчас пошучу», «сейчас напишу смешно», «сейчас сделаю ржачно» |
| самоименование приёма (MB-06) | «приём юмора» |
| «выполнение заказа» (MB-07) | «как вы просили», «как заказывали» |
| внутренние инструкции (MB-08, L342) | «согласно внутреннему промпту», «по инструкции», «мне велели» |
| внутренние механики (MB-09) | «system2», «system 2», «tool-router», «tool router», «ранкер», «в контексте мне не дали» |
| самоописание не-человеком (MB-13, контроль ANTI_BOT) | «я нейросеть», «языковая модель», «я ии», «я программа» |
| нарратив режимов (MB-14) | «активирую режим», «перевожу в режим», «режим serious включен» |
| наблюдательская механика (MB-15) | «по моим наблюдениям», «я слежу за чатом», «наблюдатель показал» |
| служебный маркер эпизодов (MB-16) | «исход неизвестен» |
| самоссылка на промпты (MB-17) | «фактчек-канон», «мои промпты», «мой промпт», «мои инструкции» |

Матчинг — с границами слов (кириллица/латиница, регистр не важен): «история ии» не ловит «я ии»,
«программирование» не ловит «я программа» (тест `test_word_boundaries_no_false_positive`).
Словарь применяется к ОТВЕТАМ модели, не к байтам канонов (каноны легитимно содержат
запреты-примеры — блок ANTI_BOT; см. докстринг модуля).

Overclaim-семья 07D.2 (`claims_total_verification`, 3 закрытых паттерна): «проверил(а) всё/весь
интернет/сеть/паутину», «перерыл/обрыл/перелопатил/обшарил/прогуглил/изучил весь интернет…»,
«весь интернет проверен…». Не ловит: «проверил — не нашёл подтверждений», «нашёл подтверждение
в двух источниках», «проверил по трём ссылкам» (тест `test_bounded_check_phrases_not_overclaim`).

## 3. Решение по точечным правкам фраз-пулов (п.1 брифа)

**Не потребовались.** Сквозной структурный гвард `test_owner_canon_pools_never_flagged`
(70+ canned-фраз ВСЕХ пулов smartmodule_phrases + renderer-notice + checkup-notice) и
`test_unavailable_source_never_becomes_total_check` (непересечение классов со словарём)
зелёные на текущих пулах: ни один пул не содержит backstage-формул или overclaim-заявлений.
Правки канонов не производились (W3-фриз цел; `git status`: factcheck_* вне диффа).

## 4. Закрытие строк карты (тест-гварды; наблюдаемое)

| Строка | Гварды (tests/test_cfg07_egress_dictionary.py) |
|---|---|
| CFG-07A.3 | v2-контур на моках: `test_attribution_miss_after_real_check_is_honest_refusal` (контекст реально просмотрен → честный отказ, без платного поиска), `test_no_claim_route_is_honest_refusal`, `test_search_failure_is_honest_unavailability_not_verdict`, `test_llm_failure_is_honest_unavailability` — на всех отказных маршрутах `honest_failure_is_allowed` (честный класс ∧ ¬overclaim ∧ ¬метаречь ∧ ¬вердикт-заявления); positive: `test_confirmed_verdict_only_from_real_check` (вердикт только из реального CheckedVerdict; без вердикта/unknown-enum заголовок не выдумывается; insufficient_evidence — честное ограничение) |
| CFG-07A.5 | `test_admin_question_allows_honest_capability_answer` (честный ответ из человеческих имён capability `direct_capabilities.CAPABILITY_LABELS` проходит целиком), `test_metatext_blocking_does_not_replace_truth` (backstage флагается — правда не режется), `test_checkup_admin_genre_intact`, `test_checkup_fallback_notice_is_honest_unavailability`, `test_honest_admin_tech_reference_not_blocked` |
| CFG-07D.1 | `test_humor_pools_have_no_backstage_direction` (5 техник + рамка + Core ×2), `test_humor_on_renders_clean_layer` (ON: слой чист, «Не объясняй шутку», 0 LLM), `test_humor_gate_off_renders_nothing`, `test_humor_owner_toggle_off_disables_layer` (humor.craft.enabled=false → честный skip_reason), `test_allowed_sarcasm_not_removed` (Core/deadpan/честный слив Direct/жанр checkup) |
| CFG-07D.2 | `test_total_verification_claim_detected` (×4), `test_bounded_check_phrases_not_overclaim` (×5), `test_unavailable_source_never_becomes_total_check` (все 107 фраз классов), `test_honest_admin_tech_reference_not_blocked`, `test_checkup_fallback_notice_is_honest_unavailability` |
| POSITIVE | `test_positive_controls_alive_dictionary` (PC-01/02/09/11 зарегистрированы и чисты; PC-05/06 — структурный скан всех пулов; PC-10 — `test_allowed_sarcasm_not_removed`) |

## 5. Прогоны

- Фокус: `07cg-tests.txt` — **255 passed** (новые 67 + 07A-2 контракт 38 + фактчек-оркестратор/
  атрибуция CFG-06 + humor craft W4 + route-coverage 18 + F1 custom_suppress 51). 0 failed.
- Предупреждения: только pre-existing `Unknown config option: timeout` (среда, вне диффа).

## 6. Что осталось (честно)

1. **Коммит-биндинг**: strict-gate (review/release) — оркестратор после коммита; статусы строк
   карты PENDING до ревью (прецедент 07A-2).
2. **07C-G-хвост**: интеграция guard'а на delivery-швах (07C.1–.6, 07D.5–.7) — детекторы
   машинных артефактов (FA-*, MB-10/11/12), bounded retry, fail-soft; словарь этого файла —
   готовый вход (план §3 «Переиспользовать: словарь метатекста из 07A-2»).
3. `is_explicit_admin_context` — закрытый набор маркеров вопроса для будущих решений guard'а;
   расширяется осознанно, с источником (07A.7: не растущий black-list).
