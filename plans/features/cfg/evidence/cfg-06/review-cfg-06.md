# REV-CFG-06 — независимое ревью слайса CFG-06 (реконструкция фактчека v2)

Дата: 20.10.2026. Ревьюер: independent Reviewer (lane REV-CFG-06), read-only.
Кандидат: `5af56d8b1dc5f9497176585ac77d95038af7eaa7` (поверх прод `29cc49ba`/2.58.98, W0–W7 одним коммитом, 61 файл, +8026/−53).

## ВЕРДИКТ: Needs Fixes

Деплой кандидата с флагами OFF — безопасен (OFF-паритет подтверждён кодом и тестами).
Но включение `flags.factcheck_pipeline_v2` ЗАБЛОКИРОВАНО до исправления F1:
без него условие 5 композита CFG-06.B («единый контракт на всех маршрутах»)
не выполняется для Direct/tool-входа, а план включения (w7-review-package §6)
не содержит чекпоинта на этот фикс.

## Что прогонял (числа, рабочее дерево == кандидат)

| Набор | Результат |
|---|---|
| CFG-06 core: orchestrator+planner+gate+context+renderer+W6+W7+route-coverage (18 CONTRACT) | **128 passed / 0 failed** |
| Швы: handlers/service/two_call/grounding×2/tools/prompts/B07/smart_cache/settings/deep_context/mca20/d10_temporal | **322 passed / 0 failed** |
| Известные вне диффа: outgoing_guard + asap7_direct_settings | ровно 4 failed (aiogram-дрейф, v35) — базовая линия не расширена |
| requirements_gate --stage review --slice CFG-06 --candidate 5af56d8b | EXIT 1 (94 errors) — см. «Ledger-долг» |

## Acceptance ledger (ключевое)

- Композит CFG-06.B: 8 сценариев через `run_factcheck` — **VERIFIED на handler-маршрутах** (осмысленно: gate → поиск до вердикта → SafeFetcher; служебные токены отсутствуют в visible; чанки ≤4096; ссылка только из EvidenceMap; S5 needs_context-лестница; S6 спор 260 с атрибуцией анцедента tg=8000/автор «Вася»; S8 owner-block последним блоком system).
- OFF-паритет: **VERIFIED** — 3 флага default OFF (settings diff); handler при OFF идёт старым путём (`_fetch_context_with_gate` → старый `_fetch_chat_context`, decision=None); тесты `test_gate_off_byte_parity`, `test_flag_off_byte_parity_with_old_path`, `test_legacy_branch_same_call_args_as_prod`; renderer/planner импортируются лениво только внутри v2-ветки.
- **Deliberate prod-дельта при флагах OFF (заявить в релизе):** `_temporal_verbalize` — style_note-утечка «период проверки (unknown)» устранена, payload гуманизирован, добавлен `speech_owner_block` последним блоком. Это фикс исходной жалобы владельца (06A.5/06D.2 + UNIFIED-CORE P0), байт-защита тестом (старые байты отсутствуют в source; payload без enum/precision/as_of). Не блокер — но это единственное изменение поведения прода при OFF-деплое.
- Egress/renderer: **VERIFIED** — html.escape текста и атрибутов, whitelist http/https, href только из EvidenceMap текущего прогона, entity-safe нарезка по строкам (теги не рвутся), TelegramBadRequest → plain-деградация чанка, одна доставка на прогон (в т.ч. cache-hit через renderer).
- Planner/privacy (06G.3-privacy): **VERIFIED** — имена участников вычищаются из запросов (`test_privacy_authors_not_leaked`: dropped_privacy + «вася» отсутствует во всех query); бюджеты ≤3 запроса/10с/8000 символов/≤2 primary fetch/≤12 refs; детерминизм finditer.
- Таблица 06G: честная — PARTIAL_PROVEN/PARTIAL/PROVEN_ON_MOCKS+LIVE_PENDING не замаскированы под PROVEN; live-пункты адресованы владельцу/preprod (PET-правило соблюдено).
- W2-корпус: 40 кейсов, routing 1.0 / false_refusal 0.0 / unnecessary_search 0.0 / attribution_errors 0.
- Вне композита: UNVERIFIED → BLOCKED (F1) — единый контракт на Direct/tool-маршруте.

## Находки

### F1 — BLOCKER (для включения v2-флага; композит CFG-06.B, условие 5; 06B.1/06H.2)
**Direct-tool/Direct-chat вход не переведён на единый оркестратор.**
`services/tool_router.py::_fact_check` (L2436) вызывает `service.check_claim_envelope(envelope)` напрямую; файл не тронут диффом. В Direct-чате интент «фактчек» (direct_capabilities INTENT_FACT_CHECK) исполняется именно этим tool'ом. При v2 ON: gate/suitability отсутствует, широкий контекст не подаётся, egress-whitelist не применяется — второй контракт фактчека. Требование явное: 06B.1 («Direct/tool … должны проходить один gate»), 06H.2 («все входы вызывают один оркестратор»), acceptance W3 брифа. В границах w7-review-package §3 отклонение НЕ задокументировано; w3-notes.md L18 заявляет «все входы → run_factcheck» — неверно.
**Минимальный фикс:** за тем же v2-флагом в `_fact_check` после build_envelope прогнать `fsg.evaluate_with_expansion` (wide context уже доступен); no_claim/ambiguous → структурный JSON `{"status":"skipped","reason":...}` агенту без платного поиска; иначе `check_claim_envelope(envelope, chat_context=feed)` (kwarg существует). + контракт-тест.
**Recheck:** тест tool-маршрута (no_claim без вызова check_claim_envelope; ambiguous → уточнение) + прогон route-coverage.
Классификация деплоя: **не блокер деплоя с OFF** (поведение прода не меняется); блокер включения флага и закрытия CFG-06.B.

### F2 — RELATED (ledger, не код)
Ledger-нарезка карты (идёт параллельно оркестратором): в `additional_requirements` **9 evidence-записей с перепутанными полями** — `artifact_path` содержит sha256-хэш (`9a91b54c…`), `artifact_sha256` содержит путь (`plans/features/cfg/evidence/cfg-06/w7-acceptance.md`). Строгий гейт проверяет существование файла по artifact_path и хэш — сейчас связки битые. Фикс: поменять значения местами в 9 записях.

### Ledger-долг оркестратора (не код-блокер; причина EXIT 1 гейта)
1. `candidate_commit` карты = устаревший `90cfc471…` → заменить на `5af56d8b1dc5f9497176585ac77d95038af7eaa7`.
2. 93 scoped-строки (84 items CFG-06 + ADD-1.C1/C2/C3 + CFG-06.T1–T3) — статус/привязки на кандидата (нарезка в процессе на момент ревью).
3. Исправить F2 (свап полей).
4. `deployed_commit` обновить на стадии release после деплоя.
5. Строки с live_required=True (06G.1, 06G.4 и пр.) — статус READY_FOR_LIVE, не VERIFIED (в нарезке это соблюдено — сохранить).
6. Ряды CFG-06G.3/06G.1 — оставить честные PARTIAL/пометку в note (локальный tool «кто сказал» не реализован; Saccharomyces-кейс архитектурно), не поднимать до VERIFIED молча.

### Неблокирующие
- N1: `CheckedVerdict.already_delivered` — мёртвое поле с устаревшим комментарием (cache-hit по факту идёт через renderer — так и задумано W6 §4). Почистить при следующем касании.
- N2: при v2 ON `scope=none` (context_unavailable) не останавливает внутренний поиск legacy-ветки на сыром тексте цели (S5: «нет планового» ≠ «нет поиска»). Bounded; заметка на пост-W6 вместе с унификацией temporal_search.
- N3: `test_s6_…` пишет latency-зависимый `w7-dispute-metrics.json` в evidence при каждом прогоне → грязное дерево/дрейф манифеста (4↔5 мс). Писать в scratch либо исключить latency.
- N4: privacy-фильтр пропускает имена участников <4 символов. Редко; заметка.

## Границы решений (бриф п.5) — оценка
1. Envelope сохраняет собственный temporal_search — ПРИНЯТО: planner в envelope-ветке отключён (двойной платный поиск за прогон исключён), правила evidence/egress/кеша общие, унификация задокументирована как пост-W6.
2. Детерминированный gate с checkable-фолбэком — ПРИНЯТО: приоритет 06J.2 соблюдён (needs_context → расширение → только потом честный вывод; неуверенность → checkable 0.4); корпус показывает 0 ложных отказов; риск лишнего поиска ограничен бюджетами.
3. Retrieval-граница planner vs internal — ПРИНЯТО для legacy (один поиск на прогон, ошибки → честный fallback на внутренний поиск).
4. Незадокументированная граница: tool-маршрут — ОТКЛОНЕНО (F1).

## Привязка вердикта
Кандидат `5af56d8b1dc5f9497176585ac77d95038af7eaa7`; любое изменение кода/карты инвалидирует соответствующие пункты. Внешние источники не требовались (спорных внешних фактов нет; транспорт HTML — существующий, прод-проверенный).

## Рекомендация по включению флага
1. Деплой кандидата штатно, все флаги OFF (единственная прод-дельта — style_note-фикс вербализатора: заявить в релизных заметках).
2. **Сначала F1** (tool-маршрут + тест) → отдельный коммит поверх кандидата.
3. Затем hot-включение `flags.factcheck_pipeline_v2` сразу во всех чатах (стоячее согласие), техсмоук: логи retrieval/gate, healthz, ошибки; откат = флаг OFF (hot, без рестарта).
4. Ограниченные платные canary (06G.1/06G.4) в тестовом контуре после включения; живые проверки — владельцу опционально.
