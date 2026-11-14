# SFC-12-09 — остаточный разбор после 2.58.202 (deployed `0beed63d`)

- Дата: 2026-11-14/15 (после финального live-canary `15:31–15:38Z`).
- Режим: read-only investigation. Код, тесты, карты и `progress_scope.json`
  **не менялись**; записан только этот файл.
- Вход: `canary-final-20261114T153116Z.md` §5,
  `raw/fc_live_canary-20261114T153116Z.json`
  (corr `06d1cba09af5435e9e6dc8f385fdfb13`, sha256 `aa449f3c…`),
  `raw/fc_live_canary-20261114T083723Z.json` для сравнения,
  `requirements-map-fc-amendment.json` (SFC-12-09, SFC-14-03),
  `plans/owner_inputs/2026-11-14-factcheck-request-integrity-v2-full.md`
  §12.8, §13, §14.
- Развёрнутый код: `release/smart-corrective-01` @
  `0beed63df8037002ccfaacef019b8ea948d957f6` (2.58.202). Читался из
  read-only worktree, **не** из `master` (локальный `master` — другая
  кодовая линия; сверка через `git show 0beed63d:…`).
- Харнесс: pinned `fc_live_canary.py` v1.3.0, sha256
  `391deff843a4254470e01767ae20823dc85c08853c4bad8cb62dccc88aba972c`
  (совпадает с пином в отчёте). Номера строк ниже — этого файла.
- Локальный repro: контролируемый offline-пробник на развёрнутом коде,
  скриптованная LLM-стадия; без сети, БД и прод-доступа. Артефакт пробника:
  `WorkspaceData/runs/…/probe-86c48a4520/probe.py` (закрывается после
  переноса выводов сюда).

## 1. Итог: одна ошибка прогона = два разных факта

| Наблюдение | Классификация | Причина |
|---|---|---|
| `search_built_from_question=true` | подтверждено | фикс SFC-12-09 (claim-unit из `request_part`) в развёрнутом коде работает |
| `direct_answer_on_question=false`, `ambiguity_acknowledged=false` | **(b) артефакт измерения**, не дефект синтеза ответа | глобальный лимит харнесса `--max-provider-calls 60` исчерпан ровно к стадии вердикта; LLM-стадии ответа **не вызывались** |
| «нерелевантные источники» (`cbinsights` manybot/whatshelp) | **(a) продуктовый дефект** (retrieval/subject anchor) | запрос по вопросу не содержит предметного анкера («женское обрезание»); полный материал сохранён в `material_text`, но в план передаётся только `material_part` (часть материала); вопрос помечен `confirmed` по нерелевантным refs |
| харнесс засчитывает «прямой ответ» только по точной форме стран | **(c) дефект прокси харнесса**, не контракта владельца | `_question_places` ищет `франция` как подстроку; «по Франции и Великобритании» и честный отрицательный ответ дают `false` |
| SFC-14-03 `providers_unavailable`, 2 failures, 0 evidence | **(b) тот же артефакт лимита**, не деградация провайдера | smoke-прогон сделал **0** провайдерских вызовов: `total=60/60`, `charge()` бросал `ProviderCallCapReached` до HTTP |

Контракт §12.8 не ослаблен: SFC-12-09 остаётся `READY_FOR_LIVE`
(не `FAILED` и не `VERIFIED`). Но «зелёный» ответ по SFC-12-09 в этом
прогоне не получен: стадия ответа не выполнялась, а retrieval по вопросу
собрал нерелевантные источники.

## 2. Что записано в прогоне `153116Z` (факты)

```
corr:            06d1cba09af5435e9e6dc8f385fdfb13
subject:         mixed, resolved_by=llm, text_chars=420, material_chars=134,
                 request_chars=127, has_request_part=true, note="",
                 text_overlaps_material=0.833, text_is_material=false
                 preview: "она распространена во многих странах Африки и
                 Ближнего Востока, и на её сохранение повлияли США
                 Распространено ли женское обрезание … есть ли страны с этой…"
plan:            queries=2, intents=[entity_check,entity_check], claims=2,
                 claim_anchors=2
queries:         «Распространено она распространена во многих странах африки
                  ближнего востока»
                 «Франция Великобритания Германия реально страны этой
                  традицией которые не влияли»
retrieval:       claims=2/2 searched/2 direct, candidates=40, opened=0, refs=3,
                 evidence_chars=1200, off_topic_sources_dropped=8,
                 provider_failures=0, fetch_errors=0,
                 stop_reason=sufficient_evidence
                 per_claim: c1 → 1 citation, c2 (вопрос) → 2 citations
envelope:        insufficient_evidence / unknown, reason=temporal_fallback_mode,
                 parts=2, uncertainty_keys=[], inference_gap=false,
                 counterpoint=false, fallback_used=true, verdict_text_chars=52,
                 stage_trace: verdict success → verbalize skipped
events:          temporal_verdict failed (WARN), temporal_verbalize failed (WARN)
                 (события validator нет)
delivered:       412 симв.:
                 "<b>Недостаточно данных для проверки</b> Недостаточно данных
                 для полной проверки утверждения. Источники:
                 1. edinstvo-news.ru — пересказ
                 2. cbinsights.com/company/manybot — пересказ
                 3. cbinsights.com/company/whatshelp — пересказ"
db:              run_id tfr-16aa40a0cffd40c5, evidence 3/1200, reason
                 temporal_fallback_mode
calls:           this_run llm=1, search=4, fetch=4; cumulative total=60/60
```

Три источника в доставленном ответе — это ровно 3 evidence-строки прогона
(`c1:1`, `c2:2`); ответ их не использует, но рендер перечисляет их как
«Источники». Две ссылки, привязанные к вопросу (`cbinsights`
manybot/whatshelp), — страницы чат-бот компаний; третья (`edinstvo-news`,
новость о проекте БРИКС) — тоже не по теме женского обрезания. То есть
ни один из трёх refs не является релевантным evidence по вопросу.

## 3. Почему answer-assertions ложные: исчерпан лимит харнесса

### 3.1. Арифметика вызовов

`CallBudget.charge` (`fc_live_canary.py:332-345`) считает **накопительный**
`total` и бросает `ProviderCallCapReached` (`:268-269`) при
`total >= max_calls`; `max_calls` по умолчанию 60 (`:3792-3794`).
`run_scenario` сбрасывает только `per_run` (`:1496-1497`), не `total`.
Каждый LLM-вызов обёрнут `budget.charge("llm")` **до** реального
`generate` (`:469-473`), поэтому даже упавший/таймаутный вызов был бы
посчитан.

Накопление по проверкам этого прогона:

```
ordinary            17  (llm 3, search 6, fetch 8)
multipart+short     24 + 10 = 34   (итого 51)
original             9  (llm 1, search 4, fetch 4) → итого 60/60
smoke                0  (llm 0, search 0, fetch 0) → любой charge бросает
```

`original` стартовал с 51, потратил 9 и ровно заполнил 60. Первый
LLM-вызов в нём — `subject_resolve` (`this_run.llm=1`). Следующий
LLM-вызов (аналитик вердикта) обязан был бросить `ProviderCallCapReached`
**до HTTP**, поэтому `this_run.llm` остался 1, а события
`temporal_verdict`/`temporal_verbalize` — `failed`. Это не таймаут
провайдера: таймаутный вызов всё равно увеличил бы `per_run.llm`.

### 3.2. Что делает продукт при отказе LLM-стадии

- `_temporal_verdict_json` ловит любое исключение и возвращает `None`
  (`services/factcheck_service.py:3890-3895`); обе попытки (аналитик +
  fallback) → `{}` и `fallback_used=true`, `reason=temporal_fallback_mode`
  (`:3484-3502`).
- `_temporal_verbalize` при исключении эмитит `temporal_verbalize failed`
  и возвращает `""` (`:4082-4099`); вызывающий берёт
  `_temporal_fallback_text` — «Недостаточно данных для полной проверки
  утверждения.» (`:4243-4246`).
- Событие `temporal_verdict` с `outcome="error"` → `failed`/WARN
  (`services/turn_payload_events.py:71-76`), `finish_reason="degraded+fallback"`.
  Ровно это и наблюдалось.

Это **честная деградация продукта**, а не «игнорирование вопроса»: до
стадии синтеза ответа прогон не дошёл.

### 3.3. Почему в отчёте выглядело «no cap»

1. `ProviderCallCapReached` брошен **внутри** обёртки `llm.generate`, а
   продукт ловит `Exception` и молча деградирует. `run_scenario` видит
   `outcome` без исключения → `run.error=null` → `provider_cap_reached=0`.
2. `RunBundle.events` сохраняет только `event_name/outcome/level`
   (`fc_live_canary.py:1594-1595`), выбрасывая `fields`/`normalized` с
   `finish_reason`, `decision`, `reason_code`. Поэтому в raw JSON нельзя
   отличить отказ LLM от отказа провайдера.
3. Для smoke ошибка поиска неотличима: любой `Exception` в
   `_invoke` → `provider_failures += 1`
   (`services/factcheck_planner.py:2106-2125`), а при `used==0` и
   `provider_failures>0` выставляется `providers_unavailable`
   (`:2386-2388`). `ProviderCallCapReached` попал в эту же ветку.

### 3.4. Локальное воспроизведение (deployed `0beed63d`, offline)

Пробник A: реальный `CallBudget(allow=True, max_calls=60)` с
`total=60`; скриптованная LLM-стадия; `check_claim_envelope` на
синтетическом mixed-envelope (материал 134 + вопрос 127) и 3 refs.

```
steps: [] | cap_hit: True
fallback_used: True | verdict: insufficient_evidence |
reason: temporal_fallback_mode | temporal: unknown
inference_gap: False | counterpoint: False
verdict_text: "Недостаточно данных для полной проверки утверждения."
events: temporal_verdict failed (finish_reason=degraded+fallback),
        temporal_verbalize failed (finish_reason=verbalize_failed)
canary direct_answer_on_question: False
canary ambiguity_acknowledged: False
```

Совпадение с прогоном: те же `fallback_used`, reason, 52-символьный
шаблон, те же два WARN-события, те же два ложных assertion. Это
детерминированное следствие лимита, а не свойство синтеза ответа.

### 3.5. Ранний прогон `083723Z` — та же картина, но аналитик успел вызваться

```
original: llm 2, search 4, fetch 6; total 60/60
events:   temporal_verdict success → temporal_validator failed →
          temporal_verbalize failed
delivered: 524 симв., тот же шаблон
```

После short было 48. Subject → 49; search/fetch → 59; аналитик → 60
(`this_run.llm=2`) и **успел выполниться** (`temporal_verdict success`).
Следующий `charge` (validator) уже бросил лимит, поэтому validator,
fallback-повтор и вербализатор **не вызывались**. То есть validator не
«упал по провайдеру» — он вообще не дошёл до HTTP. Прежняя формулировка
«деградация провайдера» для answer-стадии не подтверждена: в обоих
прогонах (`083723Z`, `153116Z`) стадия ответа была сорвана лимитом
харнесса (в `153116Z` — ещё раньше, на аналитике).

## 4. Почему источники нерелевантны: продуктовый дефект retrieval-анкера

### 4.1. Факты

- `subject.material_text` = исходный материал 134 симв. сохранён
  (`envelope.material_chars=134`), но текст предмета начинается с
  «она распространена…» и в первых 201 символах не содержит начала
  материала («Женское обрезание — древняя традиция…»);
  `text_overlaps_material=0.833`. Точная граница `material_part` не
  записана (см. §8), но по длинам (420 = 292 + 127 + 1) полный материал
  134 симв. в текст предмета не помещается: 292 симв. приходятся на
  LLM-предмет, 127 — на `request_part`.
- Планировщику передаётся **не** полный материал, а `subject.material_part`:
  `services/factcheck_orchestrator.py:1814-1817`
  (`subject_material_text=str(subject.material_part)`), хотя
  `CheckSubject.material_text` хранит полный материал
  (`factcheck_orchestrator.py:306-332`). Причём и этот
  `subject_material_text` участвует только в `_claim_anchor_map`
  (`factcheck_planner.py:890-953`), а не в термах запросов.
- `_claim_units` (`services/factcheck_planner.py:545-628`) получает
  `claim` (предмет), `items` и `request_text`; **полный материал в
  построении единиц не участвует**. Материальная единица может выпасть,
  если LLM сузил `material_part` до подстроки (валидатор принимает любую
  дословную подстроку — `factcheck_orchestrator.py:400-426`), а предмет
  содержит только эту подстроку.
- Запросы строятся из `(uents + uterms)[:10]`
  (`factcheck_planner.py:1102-1120`); у длинной единицы предметные слова
  за пределами первых 10 токенов отбрасываются. В превью видно
  «…повлияли США Распространено ли…» — **без точки**: материальная часть и
  переписанный вопрос склеены в одну единицу, поэтому лимит 10 термов
  отрезает «женское обрезание». В прогоне оба запроса не содержат темы:
  `…распространено она распространена во многих странах африки…`,
  `Франция Великобритания Германия реально страны этой традицией…`.
- `run_retrieval` пометил c2 (`user_request`) как `confirmed` с 2
  citation; `off_topic_sources_dropped=8` не отсеял `cbinsights`
  manybot/whatshelp. Итог — `stop_reason=sufficient_evidence` без
  релевантного evidence по вопросу.

### 4.2. Это не следствие фикса, но и не закрыто им

Фикс SFC-12-09 добавил вопрос как claim-unit и запрос — это подтверждено
(`search_built_from_question=true`). Но вопрос сформулирован через «этой
традицией» и не содержит названия практики; запрос по вопросу без
предметного анкера уходит в общий поиск и приносит нерелевантные
страницы. Тот же дефект виден и на материальной единице: предмет начинается
с «она…» (по превью) и не содержит темы, а полный материал в план не
передаётся. Поэтому §12.8 «исследование релевантных источников» фактически
не выполнено, хотя харнесс-прокси `relevant_sources_researched` (refs≥1)
зелёный.

### 4.3. Локальная проверка answer-пути (пробник B)

При рабочем скриптованном LLM (аналитик + валидатор + вербализатор) и
свежем бюджете развёрнутый код:

```
steps: temporal_verdict, temporal_validator, temporal_verbalize
fallback_used: False; inference_gap: True
verbalizer payload: содержит user_request (весь вопрос) и
                    original_material (исходный материал)
canary ambiguity_acknowledged: True (через inference_gap)
canary answer_not_a_harness_echo: True
```

То есть **структурной потери вопроса в answer-стадии нет**: вопрос и
полный материал доходят до вербализатора, `inference_gap`/`counterpoint`
пробрасываются в результат. Провал двух assertion в прогоне — не из-за
игнорирования вопроса синтезом, а из-за того, что стадия не выполнялась.
По имеющимся данным для SFC-12-09 не нужен новый механизм
ответа/неоднозначности; нужен retrieval-анкер и чистый прогон.

## 5. Харнесс-прокси «прямого ответа»: ложный красный на честном ответе

`direct_answer_on_question` (`fc_live_canary.py:2498`) = точное вхождение
страны из вопроса **или** `_place_like_tokens`. Оба предиката хрупкие:

```
_question_places(TRIGGER_TRADITION) = [Великобритания, Германия, США, Франция]
"по Франции и Великобритании" → []        (падеж не совпадает)
"Франция и Великобритания"    → оба        (только именительный)
```

Пробник B1 (честный отрицательный ответ «по конкретным странам данных
нет…») даёт `direct_answer_on_question=false`, хотя это прямой ответ на
вопрос. B2 (ответ называет «Франции и Великобритании») — тоже `false`.
Значит, даже после устранения лимита корректный ответ может получить
ложный красный. Это дефект **измерительного прокси**, а не контракта:
контракт §12.8 требует прямого ответа (в т.ч. честного отрицательного),
а не именительного падежа страны.

Дополнительно `material_kept` (`:2484-2487`) проверяет только
`envelope.material_chars>0` и overlap **preview** ≥0.15; в прогоне
assertion true (полный `text_overlaps_material=0.833` — отдельное поле
subject-view), хотя полного материала в предмете нет. Это ещё один
пропущенный сигнал.

## 6. SFC-14-03

```
153116Z smoke: calls this_run 0/0/0, total 60/60;
                retrieval stop_reason=providers_unavailable,
                provider_failures=2, candidates=0, evidence=0;
                delivered 302 симв. технического ответа
083723Z smoke: те же 0/0/0 при total 60/60
```

`provider_failures=2` — это два `ProviderCallCapReached`, а не отказ
поискового провайдера; `providers_unavailable` — классификация
`run_retrieval` для «used==0 + failures>0». Значит, **содержательный
production smoke не наблюдался ни разу**, а формулировка «observed только
в degraded provider state» неточна: это degraded **harness budget**.
Identity/health 9/9 и «ответ доставлен» валидны; сквозной результат при
работающем поиске — нет. Следующий шаг: чистый изолированный прогон
`production_smoke` (см. §7), а не поиск деградации провайдера.

## 7. Минимальный план исправления и проверок

### 7.1. Харнесс (сначала — иначе следующее evidence снова будет ложным)

1. Сделать исчерпание лимита явным: `CallBudget` хранит `cap_hit`;
   `run_scenario` после `run_factcheck` при `budget.cap_hit` ставит
   `error="provider_cap_reached"` / отдельный статус, а не семантический
   `error` проверки. Не позволять продукту «проглатывать» лимит в
   `temporal_fallback_mode` без следа.
2. Бюджет на проверку или существенно больший общий лимит; для
   ближайшего прогона — изолированные проверки:
   `--checks original_production_scenario` и
   `--checks production_smoke` (60 вызовов на одну проверку достаточно:
   mixed-сценарий использует ~12).
3. Сохранять в `RunBundle.events` `fields`/`normalized` (R17-редакция):
   `finish_reason`, `decision`, `reason_code` — иначе raw JSON не
   диагностируем.
4. Self-test кейс: лимит исчерпан → проверка помечена
   `provider_cap_reached`, а не «семантический error».
5. `direct_answer_on_question`: сравнение по основе/стему стран из
   вопроса (без внешнего списка стран) **или** явный признак прямого
   отрицательного ответа («по вопросу/странам данных нет», «не
   подтверждено») при условии, что ответ не является шаблоном; сохранить
   `answer_not_a_harness_echo` и остальные проверки. Трактовку
   согласовать с Reviewer заранее; контракт не ослаблять.
6. `material_kept`: проверять наличие полного материала **в предмете**
   (нормализованное вхождение/overlap≈1), а не только
   `material_chars>0`.
7. В `subject`-view добавить `material_part_chars`,
   `material_part_is_full_material`, `request_part_chars` (R17-safe) —
   сейчас точный `material_part` в raw JSON отсутствует.

### 7.2. Продукт (SFC-12-09, отдельный Builder-лейн)

1. Передавать в план **полный** `subject.material_text` (а не только
   `material_part`): `factcheck_orchestrator.py:1814-1817` →
   `subject_material_text=subject.material_text` (или отдельный параметр
   `subject_full_material_text`).
2. Гарантировать материальный анкер в поиске: если полный материал не
   покрыт единицами предмета, добавить его предложения как единицы/
   запросы (`_claim_units` + `build_claim_units`), либо включить 2–3
   предметных терма материала в запрос единицы `user_request`. Без
   лексических списков стран: анкер берётся из сохранённого материала.
   Вспомогательно — сохранять границу предложения при склейке в
   `_subject_from_decision` (если текст не заканчивается на `[.!?;]`,
   добавлять точку перед `request_part`), чтобы вопрос не сливался с
   материальной частью в одну длинную единицу; это не заменяет
   материальный анкер.
3. Тесты (`TEST-LIFECYCLE: CONTRACT`):
   - mixed-сценарий: запрос по вопросу содержит и терм вопроса
     («франция»), и предметный анкер материала («обрезание»); в плане
     есть материальный запрос с темой;
   - controlled-aggregator: нерелевантная выдача (например, компании
     `manybot`) не становится `claims_with_direct_evidence` для
     question-claim;
   - регресс ordinary/B/E: запросы и число единиц не изменились.
4. После фикса — независимое ревью и деплой; только затем чистый
   live-canary.

### 7.3. Чистый прогон после фиксов (не owner-QA)

```
fc_live_canary.py --allow-provider-calls --expect-harness-sha256 <new> \
  --checks original_production_scenario
fc_live_canary.py --allow-provider-calls --expect-harness-sha256 <new> \
  --checks production_smoke
```

Ожидаемые наблюдаемые значения: `this_run.llm≥3`, `cap_hit=false`,
`plan.queries` с предметным анкером, `claims_with_direct_evidence` по
вопросу с релевантными refs, `direct_answer_on_question=true` **или**
честный отрицательный ответ, принятый согласованным прокси,
`ambiguity_acknowledged=true` через `inference_gap`/`counterpoint`/текст.
Если ответ честно отрицательный, это не «провал», а валидный прямой
ответ; Reviewer фиксирует трактовку до прогона.

## 8. Ограничения разбора

- Точный JSON `subject_resolve` и полный `subject.text` в raw JSON не
  сохранены (только 200-символьный preview); `material_part`/`request_part`
  в `subject.as_dict()` не пишутся. Вывод о неполном присутствии материала
  в предмете опирается на preview, `text_chars=420`, `material_chars=134`,
  `text_overlaps_material=0.833` и на запросы плана; точная граница
  `material_part` не восстановима.
- Пробник B использует скриптованную LLM-стадию и синтетические evidence
  rows (URLs взяты из доставленного ответа, support — синтетический);
  он доказывает структуру answer-пути, а не качество реального ответа.
  Реальных provider-вызовов не делалось.
- `uncertainty_keys=['dates_unresolved']` в пробнике A — следствие
  синтетических дат (в прогоне `[]`); на классификацию не влияет.
- Журнальные `ReadTimeout`/fallback в отчёте не относятся к LLM-стадиям
  `original` этого прогона: там было **ноль** вызовов после subject.
  В `083723Z` аналитик успел выполниться, но validator/fallback/verbalize
  были заблокированы лимитом и не вызывались; приписывать им отказ
  провайдера нельзя.
- Production-доступ, БД и Telegram не использовались; прод остаётся
  `0beed63d` / 2.58.202.

## 9. Артефакты и гигиена

- Развёрнутый код читался из worktree
  `…/worktrees/…/smart-corrective-01-0097aecc4a7a-6fc68e04`
  (HEAD `0beed63d`, read-only; не изменялся).
- Offline-пробник: `WorkspaceData/runs/…/probe-86c48a4520/probe.py`
  (deployed worktree, `CallBudget`/`ProviderCallCapReached` из pinned
  харнесса, `check_claim_envelope`). После переноса выводов закрыт
  `run-close`.
- Изменён только этот файл; код, тесты, карты и `progress_scope.json`
  не тронуты.
