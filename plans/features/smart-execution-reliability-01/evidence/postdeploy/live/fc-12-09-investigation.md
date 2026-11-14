# SFC-12-09 — разбор production-отклонения исходного сценария (live-canary rerun 2.58.200)

- Дата разбора: 2026-11-14 (после прогона `08:37–08:44Z`).
- Задача: read-only investigation. Код, тесты, карты требований и `progress_scope.json`
  **не менялись**; записан только этот файл.
- Вход: `evidence/postdeploy/live/canary-rerun-20261114T083723Z.md`,
  `evidence/postdeploy/live/raw/fc_live_canary-20261114T083723Z.json`
  (check `original_production_scenario`, correlation_id `093904aea444462ebc41ae208e4ac0ee`),
  `requirements-map-fc-amendment.json` (SFC-12-09 / L01228, L01234–L01239),
  `plans/owner_inputs/2026-11-14-factcheck-request-integrity-v2-full.md` §1.1, §3.2, §3.3,
  §6, §9.2–9.3, §12.8, §13.
- Код: production checkout `0e4a144d` (read-only worktree
  `…/smart-execution-reliability-01-45d7d5f19c3b-db50b61f`, HEAD `13884daa`;
  `git diff 0e4a144d HEAD -- services handlers` пуст, разница только в docs/release-evidence).
  Локальные прогоны — main venv `C:\Code\Python\adminbot\.venv`, без сети, без БД, без прод-доступа.

## 1. Итог

**Классификация: продуктовый дефект (подтверждён), детерминированный в развёрнутом коде;
в том же прогоне его маскировала деградация LLM-провайдера.**

Два отклонения в одном прогоне (второе частично следует из первого):

1. **`search_built_from_question = false` — дефект продукта.** Пользовательский вопрос
   структурно сохранён (`origin=mixed`, `has_request_part=true`, `request_part` = вопрос),
   но в поисковые запросы он не попадает: план строится только из предложений
   `CheckSubject.text`, а вопрос приклеен к концу пересказного предложения, поэтому ни одна
   claim-единица не строится «от вопроса». `subject_request_text` используется планировщиком
   **только для анкоров**, не для запросов. Воспроизведено на развёрнутом коде: 0/13
   содержательных токенов вопроса в запросах (порог харнесса 0.2).
2. **`direct_answer_on_question = false` / `ambiguity_acknowledged = false` — следствие
   (1) плюс деградации провайдера в том же окне.** Вопрос не исследовался, доказательств по
   нему нет; поверх этого `temporal_validator` и `temporal_verbalize` завершились WARN-отказом
   (`fallback_used=true`, `reason=temporal_fallback_mode`), и доставлен детерминированный
   шаблон «Недостаточно данных для проверки» + список 3 источников — он по построению не
   отвечает на вопрос и не содержит оговорки о неоднозначности.

Харнесс не является артефактом: входные данные честно воспроизводят сценарий §1.1/§12.8
(см. §3), а провал запросов повторяется детерминированно на тех же данных.

## 2. Что именно записано в прогоне (факты, без интерпретации)

```
subject:        origin=mixed, resolved_by=llm, text_chars=567, material_chars=134,
                request_chars=127, has_request_part=true, has_material_part=true,
                text_overlaps_material=1.0, text_is_material=false
plan:           2 запроса, intents=[entity_check, entity_check], claims=2, planner_version=fp4
queries:        «Африки Ближнего Востока женское обрезание древняя традиция она распространена во»
                «Африки Ближнего Востока подтверждение тезиса женское обрезание древняя традиция распространённая»
retrieval:      candidates=34, opened=0, refs=3, evidence_chars=1200, claims_searched=2,
                claims_with_direct_evidence=2, stop_reason=sufficient_evidence,
                budgets_enabled=false, budget_source=global, provider_failures=0, fetch_errors=2
envelope:       factual_verdict=insufficient_evidence, temporal_status=unknown,
                reason=temporal_fallback_mode, parts=2, uncertainty_keys=[], fallback_used=true,
                has_ambiguity_note=false, stage_trace: verdict success → verdict failed → verbalize skipped
events:         temporal_validator failed (WARN), temporal_verbalize failed (WARN)
delivered:      524 симв., ни одного места из вопроса, answer_place_like_tokens=[]
assertions:     material_kept=true, user_question_identified=true,
                search_built_from_question=false, relevant_sources_researched=true,
                no_old_budget_early_stop=true, direct_answer_on_question=false,
                answer_not_a_harness_echo=true, ambiguity_acknowledged=false
effective cfg:  flags.factcheck_pipeline_v2=true; budgets_enabled=false (global и все 3 чата)
```

Из 8 утверждений 5 прошли: материал сохранён, вопрос определён, источники собраны, ранней
остановки по старым бюджетам нет, ответ не эхо харнесса. Провалены ровно три смысловые
проверки §12.8.

## 3. Точность входа харнесса (вопрос из брифа №1)

`fc_live_canary.py:200-207`:

```python
MATERIAL_TRADITION = "Женское обрезание — древняя традиция, она распространена во многих
странах Африки и Ближнего Востока, и на её сохранение повлияли США."
TRIGGER_TRADITION = "Фактчек, бот, реально есть страны с этой традицией на которые не
влияли такие гегемоны как Франция/Великобритания/Германия/США?"
```

`check_original_scenario` (`fc_live_canary.py:2458-2464`) вызывает реальный `run_factcheck`
с `target_text=MATERIAL_TRADITION`, `user_hint=TRIGGER_TRADITION`, `kind="reply"`,
`transport="real"`.

Оценка:

- **Вопрос — дословно** из ownersource §1.1. Соответствует.
- **Материал — не дословный, а нейтральный пересказ**: §1.1 говорит только, что исходное
  сообщение «содержало утверждения о древности традиции, её распространении и влиянии США»,
  и прямо запрещает подгонку под конкретный политический вывод. Пересказ содержит ровно эти
  три утверждения. Соответствует контракту; дословный текст материала в источнике отсутствует.
- **Одно отличие от прода**: production-обработчик `handlers/factcheck.py:711-727`
  (`_FACTCHECK_TRIGGER_RE` — `^фактчек\b`, `_HINT_LEAD_RE` — ведущие `\s,:;`) отдаёт в
  `user_hint` текст **после** слова «фактчек», т.е. «бот, реально есть страны …», а харнесс
  передаёт всё сообщение, включая «Фактчек, ». Разница — 4 символа префикса и один токен
  «фактчек»; на дефект не влияет (вопрос и все страны присутствуют в обоих вариантах).
- **Остаточный пробел точности**: у синтетического чата нет предыстории группового
  обсуждения, которая была в реальном чате. `context_mode=wide_gated` в плане, но
  wide-контекст синтетического чата пуст. Это допустимо для §12.8 («воспроизвести через
  существующий контролируемый контур»), но означает, что влияние живой истории чата на
  `subject_resolve` не проверялось.

Вывод: вход харнесса **достаточно точен**, наблюдаемое поведение — не артефакт синтетики.

## 4. Где вопрос должен влиять на поиск и где он теряется (вопрос №2)

Путь: `FactcheckRequest.user_hint` → `resolve_check_subject` → `CheckSubject` →
`build_retrieval_plan` → `run_retrieval` → вердикт.

### 4.1. Вопрос сохраняется корректно

- `services/factcheck_orchestrator.py:1412` — `request_text=req.user_hint`.
- `resolve_check_subject` (`factcheck_orchestrator.py:478-569`) вызывает LLM-стадию с
  `<original_material>`/`<user_request>` и разбирает JSON.
- `_subject_from_decision` (`factcheck_orchestrator.py:400-475`): при `origin=mixed`
  собирает итоговый текст (456-463):

```python
else:
    origin = SUBJECT_ORIGIN_MIXED
    text = subject
    if _subject_norm(material_part) not in _subject_norm(text):
        text = f"{material_part} {text}".strip()
    if request_part and _subject_norm(request_part) not in _subject_norm(text):
        text = f"{text} {request_part}".strip()
```

**Ключевой момент:** части склеиваются одиночным пробелом без сохранения границы
предложения. Если LLM вернул `subject` как пересказ материала без завершающей точки, а
`request_part` — вопрос, получается `материал + " " + пересказ + " " + вопрос` одной
«фразой» (в прогоне — 134 + 1 + 304 + 1 + 127 = 567 символов, ровно `text_chars`).

### 4.2. Планировщик строит запросы только из предложений предмета

- `build_retrieval_plan` (`services/factcheck_planner.py:501-542`) получает
  `subject_request_text` и передаёт его в `_build_plan_inner`.
- `_build_plan_inner` (`factcheck_planner.py:974-1143`):
  - `units = build_claim_units(items, claim)` (1017) — единицы проверки;
  - цикл запросов (1049-1083): на каждую единицу `_claim_terms(unit.text, limit=8)` (1065),
    `(uents + uterms)[:10]` (1068/1082) → `_make_query(...)`;
  - **`subject_request_text` в построении запросов не участвует вообще** — он передаётся
    только в `_claim_anchor_map` (1135-1140).
- `_claim_units` (`factcheck_planner.py:545-600`): разбивает предмет на предложения
  (`re.split(r"(?<=[.!?;])\s+", claim_thesis)`, 576-577) и добавляет «непокрытые»
  предложения к принятым item-частям, но (592):

```python
if any(low in c or c in low for c in covered):
    continue
```

  Предложение, которое **содержит** уже принятую item-часть, считается покрытым целиком —
  даже если в нём есть новый текст (вопрос пользователя).

### 4.3. Итог по месту потери

При наблюдаемом решении LLM:

1. `_claim_units` вернул 2 единицы: предложение материала (134) и склейку
   «пересказ + вопрос» (432). Вопрос **внутри** второй единицы, отдельной единицей не стал.
2. Запрос по второй единице строится из первых 10 токенов (`[:10]`), которые целиком
   заняты материалом/пересказом; «Франция/Великобритания/Германия/США» и остальные слова
   вопроса отбрасываются лимитом.
3. `subject_request_text` (структурно известный вопрос) не использован → третьего запроса нет.
4. Если suitability-item включает сам пересказ, вторая единица выпадает целиком на отсеве
   `factcheck_planner.py:592` (предложение содержит принятую item-часть) — итог тот же:
   запроса от вопроса нет. Воспроизведён первый вариант (item = только материал); второй
   проверен отдельно: те же 2 единицы и те же 2 запроса.
5. `run_retrieval` (`factcheck_planner.py:1938…`, проход 1 — 2140-2162 по
   `plan.queries_for(claim_id)`) исполняет только 2 материальных запроса; после 2 direct
   evidence обе материальные части «settled» → `stop_reason=sufficient_evidence`, хотя
   вопрос вообще не искали.

Формально: вопрос не «теряется в сборке subject» (он сохранён в `request_part` и в тексте),
он **не превращается в единицу проверки и запрос** — единственный структурный сигнал
(`subject_request_text`) остаётся неиспользованным планировщиком.

Дополнительно (не причина, а усиление): в вердиктные стадии вопрос передаётся
(`services/factcheck_service.py:3763-3767` — аналитик, `3858-3862` — валидатор,
`3972-3975` — verdict payload), т.е. модель просят ответить на вопрос, по которому нет
evidence.

## 5. Локальное воспроизведение (вопрос №4)

Развёрнутый код (`0e4a144d`) импортирован из production checkout; единственная подмена —
LLM-стадия `subject_resolve` со скриптованным JSON-решением, восстановленным по записанным
инвариантам прогона (`origin=mixed`, `text_chars=567`, `material=134`, `request=127`,
`has_request_part=true`, старт preview после материала: «Подтверждение тезиса о том, что
женское обрезание — древняя тради…»). Никаких сетевых вызовов, БД и прод-доступа.

```
SUBJECT: chars=567 origin=mixed by=llm          <- точно совпало с прогоном (567)
DEPLOYED PLAN: claims=2 queries=2
  equals recorded plan previews: True           <- запросы совпали символ-в-символ
  unit1 len=134  = предложение материала
  unit2 len=432  head='Подтверждение тезиса о том, что женское обрезание — древняя '
                 tail='…не влияли такие гегемоны как Франция/Великобритания/Германия/США?'
  question inside a unit: True ; request is own unit: False
  question coverage: {'ratio': 0.0, 'ok': False}         <- assertion харнесса = false
  anchors: [('c1', '', 'literal'), ('c2', 'user_request', 'user_request')]
_claim_units -> 2 units; request is own unit: False
```

Контрфакт (тот же текст, но пересказ заканчивается точкой — вопрос становится отдельным
предложением):

```
COUNTERFACTUAL (subject sentence ends with '.'): chars=567 units=3
  queries: [ …материал…, …пересказ…,
             'Франция Великобритания Германия фактчек бот реально страны этой традицией которые …' ]
  question coverage: {'ratio': 0.692, 'ok': True}
```

Прототип минимального фикса на исходном (склеенном) предмете: добавление структурной
единицы из `request_part` даёт 3 запроса и coverage 0.692.

Второй возможный вариант склейки (вопрос уже внутри `subject` LLM, 432 символа, доп.
добавления нет) даёт тот же результат: `subject chars=567`, те же 2 единицы, те же 2
запроса, `coverage 0.0`. То есть дефект не зависит от того, какой из двух вариантов
склейки вернула модель.

Существующий контрактный набор на развёрнутом коде **зелёный**:
`tests/test_factcheck_subject_contract.py` — `39 passed`. Он не покрывает наблюдаемую
конфигурацию: сценарий D добавляет условие отдельным предложением после материала, который
сам заканчивается точкой; сценарий F задаёт `request_part` с точкой
(`tests/factcheck_acceptance/test_s17_subject_acceptance.py:358`: `"Влияла ли Турция."`);
сценарий E — предмет, равный вопросу. Случай «пересказ без терминатора + приклеенный
вопрос» (реальный ответ LLM) отсутствует, поэтому review-level доказательство SFC-12-09
было зелёным при дефекте в продукте.

## 6. Что именно нарушено (вопрос №3)

Acceptance SFC-12-09 (L01228/L01236) требует: «построение поиска по этому вопросу»,
«прямой ответ на поставленный вопрос», «неоднозначность … учитывается или обозначается».
Owner source §3.2 (три сущности) и §3.3E/F (вопрос/условие пользователя не игнорировать)
делают это требованием механизма, а не темы.

Факты: вопрос структурно известен, но не участвует в retrieval; суммарно по вопросу
0 запросов и 0 доказательств. Это нарушение контракта, а не ограничение синтетического
входа. Формулировка дефекта:

> **D-12-09-A (продукт, детерминированно):** в `origin=mixed` пользовательский
> `request_part` не гарантирует собственную claim-единицу/поисковый запрос. Если текст
> вопроса склеен с материально-доминирующим предложением (`_subject_from_decision`,
> `factcheck_orchestrator.py:456-463`), `_claim_units`
> (`factcheck_planner.py:576-595`, отсев на 592) и лимит терминов
> (`factcheck_planner.py:1065-1068`, срез `[:10]` на 1068) не дают ни одной единицы
> «от вопроса», а `subject_request_text` в построении запросов не используется вовсе.

Сопутствующее (не блокирует фикс, но объясняет провал двух answer-assertions):
`temporal_validator`/`temporal_verbalize` в этом окне вернули отказ, и ответ — серверный
шаблон (`factcheck_service.py:4243-4246`), который не может ни ответить на вопрос, ни
обозначить неоднозначность. Провайдерская деградация того же окна зафиксирована в отчёте
DevOps (ReadTimeout у nano-gpt, fallback на api.deepseek.com). Это **не** оправдание
retrieval-дефекта: даже при успешном вердикте доказательств по вопросу не было.

## 7. Минимальный план исправления (вопрос №5)

**Основной фикс (структурный, без лексических правил):** гарантировать, что
`subject_request_text` всегда представлен собственной claim-единицей и запросом.

Место: `services/factcheck_planner.py`, `_claim_units` (+ прокид `request_text` из
`_build_plan_inner:1017`).

```python
def _claim_units(items, claim, *, cap=None, request_text=""):
    ...                       # существующая логика без изменений
    # S13/§3.3E-F: структурно известная часть запроса — часть установленного
    # предмета; она не может исчезнуть из-за склейки предложений у вызывающего.
    req = " ".join(str(request_text or "").split())
    if req:
        covered = {" ".join(u.lower().split()) for u in units}
        for sentence in re.split(r"(?<=[.!?;])\s+", req):
            norm = " ".join(sentence.lower().split())
            if norm and norm not in covered:
                units.append(sentence.strip())
                covered.add(norm)
    ...

def build_claim_units(items, claim, *, source_link="", request_text=""):
    ...
    raw_units = _claim_units(items, claim, request_text=request_text)
```

и в `_build_plan_inner`:

```python
units = build_claim_units(items, claim, request_text=subject_request_text)
```

Что это даёт (проверено прототипом на развёрнутом коде): +1 единица `c3` (вопрос) →
3 запроса, третий содержит «Франция Великобритания Германия … страны … традицией» →
`search_built_from_question` = true (ratio 0.692). `_claim_anchor_map`
(`factcheck_planner.py:901-914`) уже присваивает такой части `origin=user_request` и анкор
сообщения-запроса. `run_retrieval` исполняет её как отдельную часть, поэтому
`sufficient_evidence` больше не может наступить без попытки по вопросу.

Инварианты, которые фикс не меняет (проверено):

```
ordinary (no user text)      origin=material part_req=False | queries 1 -> 1 | unchanged=True
B doubt (no request part)    origin=material part_req=False | queries 1 -> 1 | unchanged=True
E request-only subject       origin=request  part_req=True  | queries 1 -> 1 | unchanged=True
```

Необязательное усиление (отдельным решением, не требуется для SFC-12-09): сохранять
границу предложения при склейке в `_subject_from_decision` (если накопленный текст не
заканчивается на `[.!?;]`, добавлять точку перед `request_part`) и/или не считать
предложение «покрытым», если оно строго содержит item-часть плюс новый текст
(`factcheck_planner.py:592`). Первое влияет на текст, который видит вердиктная стадия;
второе может порождать фрагментарные запросы — оба варианта требуют отдельной проверки,
поэтому основной фикс должен опираться на структурный `request_part`, а не на пунктуацию.

**Тесты, которые нужно добавить (существующий набор, `TEST-LIFECYCLE: CONTRACT`):**

1. `tests/test_factcheck_subject_contract.py::TestClaimUnits` — mixed-предмет, где LLM
   пересказ **без терминатора** и `request_part` = вопрос: `_claim_units` обязан вернуть
   единицу, нормализованно равную вопросу (RED на текущем коде).
2. Тот же сценарий через `build_retrieval_plan`: среди `plan.queries` есть запрос с
   содержательными терминами вопроса (например «франция»/«великобритания»/«страны»),
   и его `claim_id` есть в `plan.claim_anchors` с `origin="user_request"` и
   `anchor_tg_message_id == trigger`.
3. Регресс-набор: ordinary / B / D / E / G — тексты запросов не изменились (кейсы уже
   есть, достаточно прогнать).
4. (Опционально, integration) прогон `run_factcheck` со скриптованным агрегатором в
   echo-режиме: вопрос-запрос реально уходит в поиск и его evidence попадает в вердикт.

**Чем доказывать исходный сценарий после фикса (вопрос №5, продолжение):**

- Новый кандидат + независимое ревью + деплой; live-canary `original_production_scenario`
  на стабильном провайдере (иначе answer-assertions снова упрутся в provider-degraded
  fallback): `search_built_from_question`, `direct_answer_on_question`,
  `ambiguity_acknowledged` — все true; заодно `stop_reason` не должен быть
  `sufficient_evidence` до попытки по вопросу.
- Наблюдаемые значения в отчёте: `plan.queries` (должен быть запрос с терминами вопроса),
  `claim_anchors` (origin=user_request), `claims_with_direct_evidence` по вопросу,
  текст ответа с местами/оговоркой, `uncertainty_keys`/`inference_gap`.
- Осторожность с формулировкой харнесса: `direct_answer_on_question` засчитывает только
  упоминание места/place-like токена. Честный ответ «по конкретным странам надёжных данных
  нет» без названий стран формально провалит assertion. Это не влияет на текущую
  классификацию (в прогоне вопрос вовсе не исследовался), но Reviewer стоит зафиксировать
  трактовку заранее, чтобы не получить ложный красный на честном отрицательном ответе.

## 8. Влияние на соседние требования и на текущий corrective (вопрос №5)

- **SFC-12-02 / SFC-13-01 (обычный фактчек и наблюдаемость):** без изменений. Обычный
  вызов не имеет `request_text` (`subject.request_text is None`, `request_part=""`) →
  фикс не добавляет ни единицы, ни запроса (проверено: `queries 1 -> 1`). Счётчики
  `queries_attempted`/`claim_units` для mixed-сценариев вырастут на число предложений
  вопроса — это честные существующие поля, новых метрик не требуется.
- **SFC-5-10 / SFC-12-07 (бюджеты и объём исследования):** добавляется ≤1 запрос на
  предложение вопроса. В проде `budgets_enabled=false` → ограничения не применяются; при ON
  вопрос конкурирует в общем бюджете (это и есть желаемый приоритет). Ранняя остановка
  «sufficient_evidence» теперь требует покрытия и вопроса — согласуется с §6.3/§12.8.
- **Корректирующий эпик `smart-corrective-01` (SourceReader/checkup):** пересечения нет.
  Его write-scope — `services/source_reader.py`, `tool_router.py`, `worker_budget.py`,
  `tool_schemas.py`, `tool_loop.py`, `checkup_service.py`, `checkup_prompts.py`,
  `prompt_registry.py`, `mca_*`, `settings.py`; фикс SFC-12-09 — `services/factcheck_planner.py`
  (+ `factcheck_orchestrator.py`, если понадобится граница предложения) и factcheck-тесты.
  `settings.py` для этого фикса не нужен. Единственный общий ресурс — тестовый раннер.

## 9. Прочие строки прогона — наблюдения, не дефекты (вопрос №6)

- `SFC-12-07` / `SFC-5-10` / `SFC-13-03`: по-прежнему plumbing (A-сценарий и реальные
  значения ordinary есть, B–J и различимость метрик — на контролируемых двойниках).
  Наблюдение DevOps корректно; дефекта не выявлено.
- `SFC-14-03`: observed только в деградированном состоянии провайдера
  (`providers_unavailable`, 0 кандидатов, технический ответ). Это ограничение окна, а не
  доказанный дефект; нужен чистый прогон либо решение Reviewer о трактовке.
- Деградация `temporal_validator`/`temporal_verbalize` в этом прогоне — внешняя
  (LLM-таймауты окна 08:38–08:44Z), отдельного дефекта продукта по ней не заявляю; в
  SFC-12-09 она лишь исключила шанс на прямой ответ при уже сломанном retrieval.

## 10. Ограничения этого разбора и что осталось непроверенным

- Точный JSON-ответ LLM-стадии `subject_resolve` в прогоне не сохранён (в артефакте только
  `text_preview` 201 символ). Восстановление опирается на все записанные инварианты и
  совпадает с ними численно (567 символов) и по запросам (символ-в-символ). Оба варианта
  склейки, совместимые с инвариантами, дают один и тот же дефект.
- Production-доступ не использовался, платных вызовов не было. Реальный ответ LLM
  `subject_resolve` мог дать иную формулировку пересказа — это не меняет вывод, потому что
  гарантия «вопрос → единица/запрос» в коде отсутствует.
- Роль живой истории чата (wide context) в решении LLM о предмете не проверялась.
- Оценка «чистый прогон при стабильном провайдере» не выполнялась и не может быть
  подменена локальной симуляцией: это postdeploy-проверка после фикса.

## 11. Артефакты и гигиена

- Изменён только этот файл; код, тесты, карты, `progress_scope.json` не тронуты.
- Локальные пробники (offline, скриптованная LLM-стадия) лежали в
  `WorkspaceData/runs/…/probe-d68c19ff67/` и закрыты `run-close` после переноса выводов
  в этот отчёт; в отчёте приведены точные значения, достаточные для воссоздания проверки.
- Кандидат: production `0e4a144d` (2.58.200); локальный evidence-репозиторий HEAD
  `a575275d`; worktree `13884daa` (docs-only разница с `0e4a144d`).
