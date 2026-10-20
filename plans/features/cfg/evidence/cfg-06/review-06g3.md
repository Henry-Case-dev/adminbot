# REV-06G3 — ревью 06G.3 «кто это сказал» (read-only lane, 20.10.2026)

ВЕРДИКТ: **Needs Fixes** — 1 блокер (инвариант reason-кодов), всё остальное VERIFIED.

Кандидат: uncommitted-дифф поверх HEAD `532a2d24` (Lane REV-06G3: services/factcheck_attribution.py (fat1, новый), factcheck_orchestrator.py (этап 3b), tool_router.py (v2-ветка), smartmodule_phrases.py, mca_events.py, tests/test_factcheck_attribution_cfg06.py, requirements-map.json (только строка 06G.3)). Бамп samples-релиза (pins/версии) — полоса PKG-SU, не ревьюился.

## Acceptance ledger (06G.3)

| Пункт | Статус | Доказательство |
|---|---|---|
| Локальная резолюция: дословный фрагмент тезиса в реплике участника | VERIFIED | fat.resolve_attribution: нормализация ё/тире/регистр/пробелы без смены длины (translate 1:1), цитата срезается из свёрнутого оригинала по индексам; тест found_verbatim_quote_author_date |
| Автор/цитата/дата в Evidence (source_kind=chat, url=None) | VERIFIED | attribution_evidence_ref: «Вася: «…» [14.11.2023 22:13 UTC]», published_at; тесты TestEvidenceBinding; renderer ссылку не строит (links() фильтрует url=None) |
| Реплика другого автора НЕ подтверждает | VERIFIED | resolve_attribution фильтрует по _author_matches; тест utterance_by_other_author_is_not_confirmation |
| Честный отказ при миссе, внешний поиск НЕ вызывается | VERIFIED | оркестратор: send фразы пула + return до плана/поиска; tool-route: return skipped до check_claim_envelope; тесты: agg.searches==[] (оркестратор), payload==skipped (tool) |
| Публичные фигуры → обычный веб-контур | VERIFIED | mention_is_participant=False → клейм не меняется; тест public_figure_goes_standard_web_route |
| Privacy: участники не утекают в поиск (все ветки) | VERIFIED | external_safe_claim → _strip_privacy (W4); тесты: legacy target_text, envelope frozen-replace (provenance цел), tool-route envelope, agg.searches без имён |
| OFF-паритет | VERIFIED | весь слой внутри `if v2:` tool_router и внутри v2-only run_factcheck→_run_inner; тест OFF: gate не зовётся, клейм как есть, вызов одним аргументом |
| Гейт-механика: без LLM, пороги, reason-коды, ev-N | VERIFIED | regex-детекция (<3 автор, <8 симв/<2 токена тезис, <8 цитата); attribution_not_found в REASON_CODES; chat-1 prepend, ev-N не сдвигаются (тест) |
| Леджер/гейт | VERIFIED | check --stage review --slice CFG-06 --candidate 5af56d8b1dc5… → EXIT 0 (scoped=93, errors=0); SHA теста 4eb1ec1b… совпал с map; двойная запись: PARTIAL @5af56d8b сохранена + VERIFIED @29b91004 (реальный ancestor HEAD, −3 коммита) с честной оговоркой «БЕЗ коммита» |
| Инвариант reason-кодов (mca17c) | **FAILED** | test_reason_280_single_delta: len(REASON_CODES)==301, факт 302 — +1 из ЭТОГО диффа (attribution_not_found). Новый failure, «0 новых failures» нарушено |

## Прогоны (этот ревью, рабочее дерево)

- tests/test_factcheck_attribution_cfg06.py → **21 passed**
- factcheck-семья (17 файлов glob) → **327 passed**, 0 failures
- focused (orchestrator/gate/context/planner/renderer/tool_route/w6/w7/service + route-coverage) → **152 passed**; route-coverage отдельно → **18 passed**
- test_mca17c_invariants_round1047 → **1 failed** (см. блокер), 7 passed

## Блокер (1, маленький)

**B1 — BLOCKER, контракт «0 новых failures» / инвариант §17.2-канона.**
- Где: tests/test_mca17c_invariants_round1047.py::test_reason_280_single_delta (строка `assert len(mca_events.REASON_CODES) == 301`).
- Причина: дифф добавил `attribution_not_found` в REASON_CODES (+1 → 302) без бампа пина. На HEAD тест зелёный (302−1=301) — новый failure создан кандидатом.
- Исправление (канон проекта, тот же файл): `301` → `302` + комментарий в стиле существующих бампов («279→280→285→290→301»: «302: +1 attribution_not_found (CFG-06 06G.3)»). Это НЕ ослабление теста: словарь расширяемый по §17.2, пин защищает от недокументированного чурна — бамп с комментарием и есть контракт.
- Речек: py -3 -m pytest tests/test_mca17c_invariants_round1047.py tests/test_factcheck_attribution_cfg06.py -q → все зелёные.
- Коммит-гигиена: бамп счётчика — в коммит 06G.3 (файл также тронут PKG-SU пинами — разные хунки, конфликтов нет).

## Неблокирующие наблюдения (зафиксировать, не чинить в этом лейне)

1. Unicode-инвариант длины: `lower()` редких символов (напр. «İ») меняет длину → сдвиг границы цитаты на N симв. Воспроизведено: quote «Килякете выпало…» вместо «в Килякете…» (границы съехали, текст из той же реплики; чаще честный miss). Для ru-чатов вероятность пренебрежима. Бэклог: 2-строчный guard `len(hay)!=len(collapsed) → None` в _find_quote.
2. Found-путь: атрибуция структурная (EvidenceMap chat-1); renderer печатает только ссылки/notice — цитата/дата/автор не выводятся пользователю напрямую (вердикт LLM видит chat-feed и может упомянуть). Соответствует декомпозиции acceptance лейна («в Evidence») и W3/W5-фризу; родителю знать.
3. ctx=None: имена участников не могут быть вычищены (нет списка авторов) — pre-existing граница W4, лейн её не ухудшает. N4 «<4 симв.» честно задокументирован (evidence/cfg-06/review-cfg-06.md:58).
4. Токен-префикс автор-матча («Вася»↔«Василий») двусторонний — теоретически ложное совпадение автора возможно, урон ограничен требованием дословного тезиса в реплике. Осознанный трейд-офф.
5. claim_span-десинк после replace клейма — N/A: envelope всегда строится с claim_span=None.

## Числа и что писать в коммит

Прогнать после фикса B1: mca17c-инварианты + attribution-файл (см. речек). В коммит 06G.3: 7 файлов кандидата + бамп 301→302 в test_mca17c_invariants_round1047.py; сообщение фиксирует: «06G.3 local attribution tool (fat1): verbatim quote/author/date evidence chat-1, honest miss without external search (attribution_not_found), privacy thesis-only on all v2 branches, OFF parity; mca17c canon 301→302». В леджере при релизе перевязать candidate на фактический SHA коммита (сейчас честная оговорка об uncommitted-состоянии, гейт EXIT 0 на scoped=93 подтверждён).
