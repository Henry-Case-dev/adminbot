# W10 — ASAP-FC-EVIDENCE-STYLE-02: полнота поиска, релевантность доказательств и живая речь

Источник: `plans/current_task.md` §ASAP-FC-EVIDENCE-STYLE-02 (строки 1617–1748).
Ветка `evol/impl`, рабочая база `a4be717c` (после Reviewer PASS по
ASAP-FC-ADMISSION-01 и интеграции Vision/Media Readiness). Дата: 31.10.2026.
Статус: `QUEUED → IN PROGRESS → VERIFIED (инженерно)`.

Живой Telegram-чат и живая недетерминированная модель **не использовались**
(§8 DoD: живые публикации не нужны; §8.10 требует проверять подачу на
фиксированном payload, а не «остроумие» модели). Всё ниже подтверждено
детерминированными fixtures: провайдеры/LLM/сеть/Telegram — фейки.

## 1. Первопричины (что реально ломало доказательность)

1. **Планировщик покрывал не новость, а три запроса.** `build_retrieval_plan`
   строил «≤3 запроса на всё сообщение»: у составной новости из 6 независимых
   утверждений 4–5 частей вообще не получали попытки поиска
   (`queries=1..3`), а `insufficient_evidence` затем ставился всем частям
   скопом.
2. **Скрытый жёсткий дедлайн 10 с.** `_BUDGET_SECONDS_DEFAULT = 10.0` был
   безусловным потолком любого прогона: чем больше часть, тем больше частей
   отваливалось молча (класс `budget_exhausted`), без различения «не успели» и
   «данных нет».
3. **Релевантность считалась по пересечению токенов всей выдачи.** Проверки
   «эта ссылка про ЭТОТ тезис» не было: `EvidenceRef` не знал, к какому claim
   относится, поэтому статья о золоте могла оказаться «источником» тезиса об
   Alphabet, а заголовок о падении индекса — «подтверждением» конкретной суммы.
4. **`insufficient_evidence` смешивал четыре разных состояния:** провайдер
   упал, дедлайн, источник не открылся, источника действительно нет.
   Публичная фраза во всех случаях была одна.
5. **Renderer показывал не более 4 частей** (`_MAX_BOUND_PARTS = 4`): у
   шестичастной новости два пробела физически не попадали в ответ, а ссылки
   брались из общего `EvidenceMap`, без привязки к своему утверждению.

## 2. Что сделано (по пунктам задания)

### §3.1 Единица проверки — `ClaimUnit` (per-claim retrieval)

`services/factcheck_planner.py`:

* `ClaimUnit` — `claim_id`, короткий текст, `source_link`, сущности, метрики,
  единицы, временной интервал и часовой пояс, тип утверждения
  (`fact`/`number`/`change`/`cause`/`quote`/`forecast`), латинские имена/тикеры,
  точка события. Строится из СУЩЕСТВУЮЩЕЙ декомпозиции (`claim_items`/
  предложения); новых LLM-вызовов и отдельной БД нет.
* `ClaimEvidence` — роль доказательства именно для этой части
  (`supports|contradicts|qualifies|background_only|irrelevant`), дата события и
  публикации, URL.
* `ClaimCoverage` — статус поиска (`not_attempted|searched|source_read|
  source_failed|deadline_exceeded|provider_failed`), детализированный исход
  §4, итог (`confirmed|refuted|partially_confirmed|conflicting_evidence|
  insufficient_evidence|not_checked_technical`), конкретный `gap_note`,
  счётчики и citation IDs.
* Итог claim сопоставлен существующему enum (`CLAIM_OUTCOME_TO_VERDICT`) — второй
  системы вердиктов не появилось.

### §3.2 Адаптивный планировщик

* Каждая существенная часть получает СВОЙ базовый запрос: бюджет
  `adaptive_query_budget(claim_count)` (малый клейм сохраняет прежний ≤3,
  составная новость — по запросу на часть, потолок
  `limits.factcheck_max_queries_total`, заводской 12).
* Запросы строятся от части: название индекса/компании, метрика с единицей,
  валюта, интервал. Для международных новостей, где в тексте есть английское
  имя/тикер (`Alphabet (GOOGL)`, `S&P 500`), базовый запрос формируется
  латиницей с метрикой и датой — русская формулировка поста больше не запирает
  поиск в русских пересказах.
* Различаются событие / величина / причинная интерпретация: числа самого
  временного интервала («30», «2026») исключены из метрик, поэтому «30 октября»
  не «подтверждает» заявленную сумму совпадением дня месяца.
* Coverage-loop в `run_retrieval`: базовая попытка по каждой части → оценка
  привязки → уточнение ТОЛЬКО для непокрытых частей (не более
  `limits.factcheck_refine_calls`, заводской 3) и только если это НЕ повтор уже
  сделанного запроса. По хорошо подтверждённой части поиск не повторяется.
* Дедлайн больше не безусловные 10 с: `resolve_retrieval_budget(claims)` =
  базовый бюджет (10 с, настраивается `limits.factcheck_retrieval_seconds`) +
  доля базы за каждую дополнительную часть, сверху технический предел
  `limits.factcheck_retrieval_seconds_max` (45 с). При исчерпании бюджета
  непроверенная часть честно помечается `deadline_exceeded`; второго каскада
  лимитов нет.
* Поиск остаётся ОДИН — существующий `SearchAggregator` (+ его провайдеры);
  отдельного search-tool в вербализаторе нет; перепроверка источников — в
  retrieval.

### §3.3 Источник ↔ конкретный тезис

* `services/search_aggregator.claim_relevance(...)`: сначала связь с КОНКРЕТНЫМ
  тезисом (якоря: метрики, латинские имена/тикеры, содержательные термины с
  морфологией), затем роль. Совпадение одного слова/домена/темы → максимум
  `background_only` (в «Источники» не попадает).
* `qualifies` — тема/сущность те же, а заявленного числа нет: это не
  подтверждение (именно этот случай даёт публичную фразу «источник по событию
  есть, но конкретная сумма не подтверждена»). Если в источнике есть ДРУГОЕ
  число с той же единицей — это расхождение оценок (`conflicting_evidence`), а
  не удобно выбранный вариант.
* Противоположное направление («упал» ↔ rose/fell/gained, включая
  межъязыковые пары) распознаётся отдельно: источник «наоборот» не становится
  подтверждением, `unknown` не превращается в опровержение.
* При наличии URL содержимое достаётся существующим `SafeFetcher`
  (`fetch_primary_evidence`), ошибка извлечения — технический исход; открытая
  страница не превращает энциклопедию/исследование в «первоисточник». Дата
  публикации сверяется с датой события: материал старше события снимается и
  помечается («найденная публикация старше заявленного события»), старое не
  выдаётся за свежее.
* `EvidenceRef` расширен аддитивными полями `claims`/`event_at` (дефолты) —
  каждая показанная ссылка принадлежит claim ID этого прогона. Renderer
  дополнительно фильтрует `presentation.links` по EvidenceMap текущего прогона,
  поэтому подменённая/устаревшая ссылка не печатается.
* `background_only`/`irrelevant` в отображение не попадают вообще
  (`off_topic_sources_dropped` в телеметрии).
* No-false-acceptance по части: положительный вердикт МОДЕЛИ по части стоит
  только при наличии ссылки с ролью `supports` (для `refuted` — `contradicts`,
  для `mixed` — любая отображаемая). Если источник лишь «про событие»
  (`qualifies`), часть понижается до `insufficient_evidence` с конкретным
  пробелом — модель не может подтвердить сумму заголовком без суммы.
  Обратное тоже верно: подтверждённые части не понижаются из-за соседних
  проблемных (4 из 6 остаются подтверждёнными).

### §4 Статусы без ложного «данных недостаточно»

`CLAIM_STATUS_*`: `claim_unidentified`, `search_not_started`, `provider_error`,
`deadline_exceeded`, `source_extract_failed`, `no_relevant_sources`,
`evidence_conflicting`, `evidence_insufficient_for_exact_number`,
`verified/refuted/partial`. Публичные формулировки различают их: renderer
печатает конкретный `gap_note` рядом со СВОИМ утверждением, а прежние
технические заголовки/оговорки по `reason_code` (`deadline_exceeded`,
`provider_unavailable`, `source_missing`) сохранены. Reason-коды — только из
существующего реестра `mca_events.REASON_CODES`.

### §5 Живая речь внутри структуры

* Второго Writer/LLM-прохода нет: публичный текст по-прежнему формирует
  существующий verbalizer. В его payload добавлены `claims` — статус каждой
  части человеческими словами (`CLAIM_STATUS_HUMAN`) и конкретный пробел, чтобы
  модель писала «сумму автор придумал», а не «данных недостаточно» после каждого
  пункта.
* Директива «Жестко разъеби тейк автора и поясни почему он не прав.»
  (существующая, дословная) и настройка «Критический разнос» не дублируются;
  §5-композиция (вывод → разбор → разнос → источники) обеспечена renderer'ом;
  выдуманное опровержение по-прежнему запрещено серверной политикой
  (`critique_policy_for_verdict`).
* Regex-постпроцессора мата не добавлено. `egress_guard`, кеш-путь,
  temporal/legacy/fallback не перетирают стиль: критический раздел режется
  только настройкой/политикой.

### §6 Телеметрия

`factcheck_orchestrator._emit_claim_coverage`: одна трасса на ход —
`claim_id → queries_count → provider/status/latency → candidates → opened →
role/evidence → reason_code → citation_ids` (в `provider_status` части) плюс
итог хода: `total_claims`, `claims_searched`, `claims_with_direct_evidence`,
`claims_partial`, `claims_unchecked_due_to_deadline`,
`off_topic_sources_dropped`, `stale_sources_dropped`, `refine_calls`,
`verbalizer_path`, `renderer_path`, `critical_section_enabled`,
`fallback_reason`, `core_revision`, `expression_revision`, `style_revision`.
Логируется строкой `[factcheck_claims]` и mca-событием `factcheck.claims`;
сырых текстов чатов, авторов, URL и ключей в событии нет. Новой UI-панели не
строилось.

## 3. Пример трассы по claim (сокращённо; значения — из фикстур §8.1)

```
c1 provider_failed provider_error      | поиск не ответил (технический сбой) — это не отсутствие данных
c2 searched        verified            | provider_status=('entity_check:search:ok:0ms',)
c3 searched        verified
c4 searched        verified
c5 searched        verified
c6 searched        evidence_insufficient_for_exact_number
   | источник по событию есть, но конкретная сумма/число из поста не подтверждены
```

(`search` в примере — имя уровня агрегатора подменено фейком; в бою там
`tavily|exa|ddg` и реальная latency.)

Соответствующие части ответа: 4 подтверждены (со своими ссылками), у c6 —
конкретный пробел, у c1 — технический исход. Общий вердикт — «Подтверждается
частично» (mixed), а не «недостаточно данных».

## 4. Приёмка §8 — 12/12 сценариев

`tests/test_evol_fc_evidence_style.py` (14 тестов, всё офлайн; autouse-fixture
выключает дата-фетч, провайдеры/LLM — фейки):

| # | Сценарий §8 | Тест | Результат |
| --- | --- | --- | --- |
| 1 | 6 независимых claim → попытка у каждой, доказательства по своим частям | `test_sc1_every_claim_gets_a_search_attempt` (+ `test_adaptive_refinement_only_for_uncovered_claim` — уточнение только непокрытой части, без повторов) | PASS |
| 2 | 4 подтверждены, 2 нет → не общий `insufficient_evidence`, точные причины | `test_sc2_four_confirmed_two_concrete_gaps` | PASS |
| 3 | статья о золоте при тезисе об Alphabet → off-topic, не ссылка тезиса | `test_sc3_off_topic_source_not_bound_to_claim` | PASS |
| 4 | русский пересказ с `Alphabet (GOOGL)` → англоязычный запрос | `test_sc4_foreign_name_produces_english_query` | PASS |
| 5 | дата статьи ≠ дата события → устаревшее не «свежее», интервал сохранён | `test_sc5_stale_article_not_fresh_confirmation` | PASS |
| 6 | заголовок о падении индекса ≠ $658 млрд → честное разделение (в т.ч. модель не может подтвердить сумму «событийным» источником) | `test_sc6_index_drop_headline_does_not_confirm_market_cap` | PASS |
| 7 | противоречивые данные → conflicting + объяснение расхождения | `test_sc7_conflicting_sources_explained` | PASS |
| 8 | провайдер/дедлайн упал → не «в интернете данных нет», успешное сохранено | `test_sc8_provider_and_deadline_are_technical` | PASS |
| 9 | полный пакет → все ссылки — реальные EvidenceRef этого прогона и своего claim | `test_sc9_displayed_links_are_real_refs_of_this_run` | PASS |
| 10 | частичный вердикт, стиль включён → живая подача в структуре, доказательства не изменены | `test_sc10_partial_verdict_live_style_within_structure` | PASS |
| 11 | стиль OFF/иная настройка + fallback → изоляция, настройки доходят, техсбой ≠ фактчек | `test_sc11_style_isolation_and_fallback` | PASS |
| 12 | доставка/кеш → чанки без битого HTML, чужие/устаревшие ссылки не показываются | `test_sc12_delivery_split_and_no_stale_links` | PASS |
| §6 | телеметрия: трасса claim + итог хода, без текстов/URL | `test_telemetry_claim_trace_and_turn_summary` | PASS |

Важно: сценарий 10 проверяет **структурную композицию** на фиксированном
payload (порядок «вывод → разбор → разнос → утверждения», наличие директивы и
style-слоя в фактическом system-промпте Writer'а, неизменность доказательств).
Живая модель не вызывалась, поэтому «живое остроумие» этим тестом НЕ доказано —
это соответствует §8.10.

## 5. Регрессия (текущий кандидат `a4be717c` + правки лейна)

| Набор | Результат |
| --- | --- |
| `tests/test_evol_fc_evidence_style.py` | **14 passed** |
| 13 именованных наборов (новый файл, admission, vision-sync core, media 25.10, handlers, prompts, b07 temporal, attribution, deep context, orchestrator, service, renderer, critical) | **344 passed** |
| `pytest tests -k "factcheck or fc_evidence"` | **601 passed** |
| Широкий срез `-k "factcheck or fc_evidence or renderer or temporal or prompt or egress or unified_core or search_aggregator or orchestrator"` | **1488 passed** (база `a4be717c` тем же срезом: **1474 passed**) |
| Контроль на базе `a4be717c` (отдельный worktree) | тот же широкий срез — без падений |

Один прогон широкого среза дал падение
`test_p0_init_arch_fix_observer.py::test_reply_links_and_addressee_reach_prompt_and_context`
(«Writer не вызывался») — тест инициатив, к фактчеку не относится; повторные
прогоны того же среза (2×) и изолированный прогон дают PASS, на базе `a4be717c`
тоже PASS. Классификация: **нестабильный предсуществующий тест**, не регрессия
лейна; отдельно не правился (вне скоупа, воспроизводится не мной).

## 6. Изменённые файлы

```
services/factcheck_planner.py       per-claim план/покрытие, adaptive бюджет,
                                    уточнения, claim-привязка, роли/итоги
services/search_aggregator.py       claim_relevance (роль/якоря/противоречия/
                                    расхождение чисел), trace провайдеров
services/factcheck_service.py       <claim_coverage> в payload аналитика,
                                    merge_claim_coverage, claims в payload
                                    вербализатора, claim_part в evidence
services/factcheck_orchestrator.py  claims в CheckedVerdict, телеметрия хода,
                                    legacy-ветка отдаёт покрытие, renderer_path
services/factcheck_renderer.py      показ ВСЕХ частей (до 8), конкретный пробел
                                    у своего утверждения, роль источника рядом
                                    со ссылкой, whitelist ссылок EvidenceMap
tests/test_evol_fc_evidence_style.py (новый, CONTRACT owner=ASAP-FC-EVIDENCE-STYLE-02)
tests/test_factcheck_p0_fc.py       (фикстура вторичного источника сделана
                                    тематической — контракт «первоисточник
                                    недоступен, вторичный остаётся» сохранён)
tests/test_factcheck_orchestrator_cfg06.py (frozen-схема: осознанное расширение
                                    полей EvidenceRef/CheckedVerdict с комментарием)
plans/features/evol/audit/w10-fc-evidence-style.md
```

Не тронуты: `web/**` (UI-лейн), video/social-файлы, ядро
`services/media_readiness.py`/`mca_vision.py`, схема БД (новых таблиц нет),
`config/settings.py` (новые лимиты читаются через существующий `hot_config`,
заводские дефолты — в модулях).

## 7. Честные ограничения и остаточные риски

1. **Живая модель не проверялась.** Стиль доказан на уровне сборки промпта
   (активная директива + Core/Expression/Style в фактическом system-сообщении) и
   структурной композиции ответа; «насколько ехидно звучит» — вне детерминированной
   проверки (§8.10 это прямо разрешает).
2. **Legacy-ветка** (`MCA_TEMPORAL_FACTCHECK_ENABLED` OFF / kill-switch) получает
   единый `search_text` и покрытие только для телеметрии: публичный текст там
   формирует существующий Writer по выдаче, per-claim статусы в ответ не
   размечаются. Основной путь (envelope) размечен полностью; менять сигнатуру
   `check_claim` ради fallback-ветки не стал — это сломало бы паритет и фейки.
3. **Привязка подтверждения к источнику** — детерминированная (якоря: метрика/
   сущность/тикер + содержательный overlap). Она консервативна: спорный кейс без
   якоря честно уйдёт в «нет подходящего источника», а не в ложное «подтверждено».
   Англоязычный источник по полностью русскому тезису без имени/тикера связать
   нельзя — это остаётся ограничением (и не маскируется).
4. **Число вызовов** ограничено конфигурацией (запросы на прогон 12, уточнения 3,
   бюджет 45 с максимум). Для новости из >12 частей часть пунктов честно помечена
   `deadline_exceeded`, а не «проверено».
5. **Дата публикации** известна только когда страницу удалось открыть; для
   сниппетов без даты «старое/свежее» не выдумывается (честное «дата
   публикации не подтверждена» через существующие оговорки).
6. **Aвторитет ≠ релевантность** соблюдается буквально: gov/энциклопедия выше
   в классификации типа источника, но не получают приоритет привязки — привязка
   считается только по тезису.
7. Отдельный `provider` в телеметрии — имя уровня агрегатора, ответившего
   первым; при падении уровня записывается последний неудачный уровень и причина.
   Индивидуальные latency всех промежуточных уровней не собираются (только лог
   агрегатора) — это существующая граница, не новая.

## §8. review-fix (Reviewer, round 2) — 5 блокеров, RED → PASS

Кандидат: `303e18e8` + правки этого раунда (файлы ниже). Каждый блокер сначала
воспроизведён probe-скриптом (значения RED приведены дословно), затем
исправлен и закрыт тестом; тесты — офлайн, провайдеры/LLM — фейки.

### F1 (BLOCKER) — подтверждение не проверяло семантику тезиса

**RED (probe):**
```
metrics: ('658 м',) units: ()          # «$658 млрд» разобрано как «658 м»
role: supports strong: True number_hits: 1
coverage: confirmed verified
merged verdict: supported
public: Подтверждается   (тезис «$658 млрд» при источнике «$658 million»)
```
**Причина:** в `_NUMERIC_PHRASE_RE` альтернатива `м` стояла перед `млн/млрд`,
поэтому масштаб терялся; `claim_relevance` засчитывал совпадение числа без
сверки единицы/валюты; закрытый список направлений не ловил «вырос» против
«подешевел/снизился»; причинный тезис подтверждался обычной статьёй о событии;
`merge_claim_coverage` синтезировал `supported` поверх вывода модели
`insufficient_evidence`.

**PASS (probe после фикса):**
```
metrics: ('$658 млрд',) units: ('$', 'млрд')
role: qualifies strong: False number_hits: 1 mismatch: True
coverage: conflicting_evidence evidence_conflicting
merged verdict: insufficient_evidence
public: Недостаточно данных для проверки
        • …$658 млрд… — данных недостаточно (источники расходятся в числе/единице…)
```
Что изменено:
* `_NUMERIC_PHRASE_RE` — длинные единицы раньше коротких (`млрд|млн|трлн|тыс` …),
  валютный префикс `$€£₽`, единицы `процент/п.п./доллар/юан/фунт`; `_UNIT_RE`
  расширен теми же токенами;
* `search_aggregator`: классы единиц `scale/percent/currency` (`_unit_class`,
  `_unit_classes`), `supports` требует `claim_classes ⊆ body_classes`; то же
  число с другим масштабом/валютой → `qualifies` + `number_mismatch`;
* направление — общая морфология (`_DOWN_RE`/`_UP_RE`: упал/паден/сниз/сниж/
  дешев/подешев/обвал/рухн/потеря и fell/drop/declin/… против вырос/раст/рост/
  повыс/повыш/подорож/grow/rose/gain/…, включая межъязыковые пары); двунаправленный
  источник опровержением не считается;
* `claim_type="cause"` проходит в `claim_relevance`: без причинной связки
  (`_CAUSAL_RE`) тезис-причина получает `qualifies`, а не `supports`;
* `merge_claim_coverage`: если модель по существу НЕ дала положительного вывода
  (ни верхний enum, ни одна её часть), серверные части не становятся
  положительными и агрегат не поднимается — вывод остаётся
  `insufficient_evidence`, конкретные пробелы видны в частях. Если модель сама
  подтвердила часть, её вывод не переписывается (сценарий 2: 4 подтверждения +
  2 пробела → `mixed`).

Тесты: `test_review_f1a_units_must_match_scale`,
`test_review_f1b_server_does_not_upgrade_insufficient`,
`test_review_f1c_cause_requires_causal_link`,
`test_review_f1d_direction_morphology`.

### F2 (BLOCKER) — расходящиеся оценки не становились конфликтом

**RED (probe):** `Nasdaq упал 3,4%`, источники 2,8 % и 3,1 % →
`insufficient_evidence / evidence_insufficient_for_exact_number`, «источники
расходятся» отсутствовало.
**PASS:** `conflicting_evidence / evidence_conflicting`,
`gap=«источники расходятся в числе/единице: заявленное значение не совпадает с
тем, что дают источники»`, обе оценки остаются в покрытии.
**Причина/фикс:** `mismatched` учитывался только при уже сильном подтверждении.
В `_finalize_claim` добавлена ветка: нет сильного подтверждения + `qualifies`
с `number_mismatch` (в т.ч. ≥2 разных числа с той же единицей) → конфликт;
`_gap_note` различает «расходятся в числе/единице» и «за/против».
Тест: `test_review_f2_diverging_estimates_become_conflicting` (+ сценарий 7
переведён на расходящиеся числа 2,8/3,1).

### F3 (BLOCKER-small) — технический сбой назывался «недостатком данных»

**RED (probe):** при пустом `reason_code` прогона заголовок
«Недостаточно данных для проверки», а строки частей —
«… — данных недостаточно (поиск не ответил (технический сбой)…)».
**PASS:**
```
<b>Проверка не завершена: поиск недоступен</b>
• Индекс упал — поиск не завершён: технический сбой (проверяемой ссылки нет)
• Nasdaq вырос — поиск не завершён: лимит времени (проверяемой ссылки нет)
```
Фикс: `factcheck_renderer` — `_TECHNICAL_PART_LABELS` по `status_detail`
(`provider_error|deadline_exceeded|source_extract_failed|search_not_started|
claim_unidentified`) и `_technical_headline_from_parts` (технический заголовок,
когда содержательного разбора нет, даже без `reason_code`); «данных
недостаточно» остаётся только для `no_relevant_sources`/
`evidence_insufficient_for_exact_number`. Соответствие сценария 8 усилено:
`assert "данных недостаточно" not in visible`.
Тест: `test_review_f3_technical_failure_not_called_insufficient`.

### F4 (BLOCKER-small) — телеметрия нарушала §6

**RED (probe):** событие `factcheck_claims` несло `claims: [cov.as_dict()]` —
тексты тезисов и URL; `trace_id`/`pipeline_run_id` отсутствовали.
**PASS:** `trace_id=tr-123` и `pipeline_run_id=tr-123` в событии; ни текста
тезиса, ни URL (`"Nasdaq" not in line`, `"http" not in line`), строки claim
содержат только `claim_id/claim_type/search_status/status_detail/outcome/
reason_code/queries_count/candidates/opened/roles/citation_ids/providers`.
Фикс: `_claim_telemetry_row` (метаданные вместо `as_dict()`), параметры
`trace_id`/`pipeline_run_id` в `_emit_claim_coverage`; `_run_inner` генерирует
один `pipeline_run_id` (`usage_events.new_correlation_id()`), прокидывает его
в `check_claim_envelope(run_id=…)` (тот же id в LLM-логах) и в событие;
`_accepts_run_id` (прецедент `_accepts_budget`) не ломает сервисы-двойники без
нового необязательного аргумента.
Тест: `test_review_f4_telemetry_has_no_texts_and_has_trace_id`.

### F5 (RELATED_SMALL) — уточнение не запускалось для неподтверждённого числа

**RED (probe):** «событийная» ссылка (`qualifies`) считалась покрытием →
`calls: 1, refine_calls: 0`, исход
`insufficient_evidence / evidence_insufficient_for_exact_number`.
**PASS:** `calls: 2, refine_calls: 1`, исход `confirmed / verified`.
Фикс: `_claim_settled(run)` — уточнение пропускается только при сильном
`supports` или `contradicts`; `refinement_query_for` для спорного числа
добавляет вариант единицы (млрд→billion, $→dollars, %→percent), поэтому
уточнение не повторяет базовую формулировку (плюс прежняя защита от повторов).
Тест: `test_review_f5_qualifies_does_not_stop_refinement`.

### Nonblocking (сделано, т.к. дёшево)

* **>8 claim units больше не теряются молча:** `build_claim_units` собирает до
  `_CLAIM_UNITS_HARD_CAP = 16`; части сверх бюджета запросов получают
  `deadline_exceeded`/`CLAIM_STATUS_DEADLINE` и честный gap «поиск прерван по
  лимиту времени»; renderer печатает «…и ещё N: не показаны (лимит разбора)».
  Тест: `test_review_claims_beyond_query_budget_are_marked_honestly`.
* **Новые лимиты через `hot_config`:** ключи `limits.factcheck_max_queries_total`,
  `limits.factcheck_retrieval_seconds`, `limits.factcheck_retrieval_seconds_max`,
  `limits.factcheck_refine_calls` читаются существующим конфиг-слоем с
  заводскими дефолтами в модулях. `services/param_catalog.py` вне скоупа этого
  раунда — **patch note для волны каталога:** добавить эти четыре ключа в
  группу лимитов фактчека с теми же дефолтами (12 / 10.0 / 45.0 / 3), после чего
  они появятся в админке; поведение без каталога уже рабочее и проверено.
* **Слабые утверждения усилены:** сценарий 8 — точное число частей без проверки
  (`claims_unchecked_due_to_deadline == len(deadline_claims)`) и запрет ярлыка
  «данных недостаточно» для технического исхода; сценарий 9 — `or True` убран,
  проверяются claim-привязка каждой ссылки и `off_topic_sources_dropped == 0`;
  сценарий 11 — вместо `or True` проверяется отсутствие выдуманного
  подтверждения в fallback-тексте.

### Проверки этого раунда (кандидат `303e18e8` + правки)

| Набор | Результат |
| --- | --- |
| `tests/test_evol_fc_evidence_style.py` | **23 passed** (было 14: +9 тестов ревью) |
| 13 именованных наборов (новый файл, admission, vision-sync core, media, handlers, prompts, b07 temporal, attribution, deep context, orchestrator, service, renderer, critical) | **353 passed** |
| `pytest tests -k "factcheck or fc_evidence"` | **610 passed** |
| Широкий срез `-k "factcheck or fc_evidence or renderer or temporal or prompt or egress or unified_core or search_aggregator or orchestrator"` | **1497 passed** |

Изменённые файлы раунда: `services/search_aggregator.py`,
`services/factcheck_planner.py`, `services/factcheck_renderer.py`,
`services/factcheck_orchestrator.py`, `services/factcheck_service.py`
(минимально — снятие апгрейда вывода модели и `run_id` для телеметрии; блокер F1
прямо называет это поведение), `tests/test_evol_fc_evidence_style.py`,
этот отчёт. `web/**`, другие лейны, схема БД, `param_catalog` не тронуты.

Остаточное ограничение F1 после фикса: масштаб/валюта сверяются по классам
(`млрд↔billion`, `$↔доллар/usd`), а не по точной методологии источника
(например, «market cap loss» vs «price drop» различаются только тезисом и
якорем, не семантическим парсером) — это по-прежнему консервативная
детерминированная проверка, а не вывод LLM.
