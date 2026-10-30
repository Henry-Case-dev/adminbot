# W7 — ASAP-FC-ADMISSION-01: ложный отказ фактчека при проверяемом тезисе

Источник: `plans/current_task.md` §ASAP-FC-ADMISSION-01 (строки 1363–1430) и п.
1–3 блока требований. Ветка `evol/impl`, база — `14b67272` (после
review-approved фактчек-лейна `3f62150f`). Дата: 31.10.2026.
Статус: `QUEUED → IN PROGRESS → VERIFIED (инженерно)`; живой Telegram-чат не
использовался (§5/DoD: живые публикации запрещены).

## 1. Дефект и первопричина

Наблюдение 31.10.2026 (групповой чат): явный `фактчек` в reply к пересланному
утверждению «вредоносный стикер со ссылкой заражает телефон / уводит
криптовалюту» → ответ «тут нечего проверять, просто базар»
(`FACTCHECK_NO_CLAIM_PHRASES`), быстрый повтор → фраза cooldown-пула, затем
при следующей попытке проверка всё-таки выполнялась.

**Первопричина — не фраза и не «плохой» текст, а семантика допуска.**
Гейт пригодности (`services/factcheck_suitability.evaluate_suitability`)
определял проверяемость по узкому структурному предикату `_has_predicate`
(числа/даты + фиксированный список глагольных основ + копула «это») и по
результату классификации `_classify_literal`. Утверждение вида «со стикера
можно поймать вирус, он залезает в телефон и уводит деньги» не содержит ни
чисел, ни «словарного» глагола, ни копулы → тип `nonsense_semantically_
incoherent`; контекстная резолюция анцедентов не нашла; в
`evaluate_suitability` срабатывал маршрут `no_claim_after_context`
(строка «…if claim_type in (SUBJECTIVE_OPINION, PERSONAL_PREDICTION,
NONSENSE, JOKE_IRONY)»). Явная команда пользователя при этом нигде не
учитывалась: `фактчек` — это ``kind=reply``/``command``, но гейт не получал
признака «пользователь попросил проверить». Совпадение двух условий (узкий
лексикон + отсутствие учёта явного запроса) давало ложный отказ.

Второй дефект того же кейса: cooldown ставился в handler'е **до** разрешения
цели (`await cooldown_touch(...)` сразу после троттлинг-проверки), поэтому
ошибочный ранний отказ расходовал полный пользовательский лимит
(`FACTCHECK_COOLDOWN_SECONDS`, заводской 300 с) — обоснованный повтор
блокировался.

## 2. Этап A — подтверждение runtime-пути

Логи прода недоступны, поэтому путь подтверждён по коду (и это прямо
оговорено в §1 `current_task`):

* реплика «тут нечего проверять, просто базар» физически существует только в
  `FACTCHECK_NO_CLAIM_PHRASES` и отправляется ровно из двух мест:
  `handlers/factcheck.py` (ветка `gate_decision.decision ==
  "no_claim_after_context"`, temporal- и legacy-маршруты) и
  `services/factcheck_orchestrator.py::_run_inner` (v2);
* `FACTCHECK_PIPELINE_V2_ENABLED` (v2) — default OFF, `MCA_TEMPORAL_
  FACTCHECK_ENABLED` — default ON, `FACTCHECK_SUITABILITY_GATE_ENABLED` —
  default OFF, но это **PG-управляемый флаг** `flags.factcheck_suitability_gate`
  (каталог `services/param_catalog.py`, группа `flags_module_factcheck`),
  поэтому в проде он мог быть включён — это единственный способ получить
  наблюдаемую фразу на temporal/legacy-маршруте;
* вывод: сработал гейт пригодности на действующем маршруте
  (`_fetch_context_with_gate`), решение `no_claim_after_context`,
  `claim_type=nonsense_semantically_incoherent`, причина — узкий предикат.

Чтобы такие случаи больше не требовали реконструкции, добавлена безопасная
структурированная диагностика (§5 ниже): `target_resolved`, `explicit_request`,
`claim_items_count`, `admission_decision`, `reason_code`, `pipeline_path`,
`verdict_stage`, `cooldown_outcome` — без текстов, авторов и ссылок.

## 3. Этап B — ранний допуск (механизм, не фразы)

`services/factcheck_suitability.py`:

| Элемент | Назначение |
| --- | --- |
| `has_checkable_core(text)` | recall-ориентированный признак «правдоподобно проверяемого ядра»: числа/даты, структурный предикат, глагольная форма + содержательные токены (`_claim_like_text`), ссылка/материал (`_LINK_RE`), ≥3 содержательных токена при непустом не-филлерном тексте. `False` только для пустого/филлерного («лол», «ага», эмодзи). Никаких предметных словарей |
| `explicit_request` (kwarg `evaluate_suitability` / `evaluate_with_expansion`) | явный запрос пользователя: при наличии ядра решение = `checkable` (`reason_code=explicit_request_checkable_core`, `confidence=0.65`), до платного поиска. Сомнение классификатора больше не превращается в отказ (§2.3) |
| `_core_items(...)` | проверяемые пункты `claim_items` из существующей атомизации `_split_atomic`; ссылка-материал (`_is_link_only`) и чистая оценка (`_is_subjective` без фактического маркера) в тезисы не попадают (§2.2/§2.5) |
| `_has_factual_marker(text)` | фактический маркер без копулы: число/сказуемое/цитата — отличает фактическую предпосылку от оценки в смешанном высказывании |
| `_claim_like_text` (+`_dispute_scores`/`_dominant_dispute`/`_resolve_contextual`/`_contextual_item`) | тезис может жить в цитате/пересылке/caption/соседнем сообщении: контекстный поиск учитывает материал-ссылку (числа/предикат/глагольная форма + содержательные токены). Уровень recall контекста НЕ расширялся до «любой содержательной фразы» — иначе цели приписывался бы случайный соседний текст (§2.6) |
| `admission_label(decision)` | канонические метки `checkable` / `no_identifiable_claim` / `insufficient_context` / `ambiguous_target` / `unavailable_target` / `gate_not_applied` (§2.4) |
| `_REASON_EXPLICIT_NO_CORE` | честный `no_claim` при явном запросе отделён от «доказательств не хватило» по `reason_code` |

Что **не** сделано (по §2.7/§4): нет словарей терминов, нет отдельного
LLM-фильтра, нет хардкода кейса о стикерах, нет отключения проверок, нет
новых обязательных LLM-вызовов. Пул `FACTCHECK_NO_CLAIM_PHRASES` не заменён.

`handlers/factcheck.py`:

* `_fetch_context_with_gate(..., explicit_request=...)` — явный запрос
  прокидывается в гейт на действующем маршруте (temporal и legacy);
* `_quoted_text` + `_extract_target_text` — если у цели нет собственного
  текста/подписи, материал берётся из `quote.text` (тезис в связанном
  материале); `MagicMock`-двойники не ломаются (принимается только `str`);
* ветка `gate_decision.decision == "ambiguous_needs_clarification"` на
  temporal-маршруте теперь отвечает коротким уточнением
  (`FACTCHECK_CLARIFY_PHRASES`), а не продолжает проверку «чего-нибудь».

`services/factcheck_orchestrator.py` (v2, единственный вход):

* `explicit_request = kind != "auto"` — reply/command/tool/ui = пользователь
  попросил проверку; автоматический вход сохраняет прежнюю строгую семантику.
  Схема `FactcheckRequest` НЕ менялась (join-barrier W3/W4, тест
  `TestSchemaFreeze::test_request_fields_frozen` зелёный);
* §2.2: пустой текст цели при собранном окне → `find_context_claim` по
  контексту (детерминированно, без LLM), затем повторный `evaluate_suitability`
  — связанный материал не считается «нечего проверять»;
* новый честный маршрут `context_unavailable` → `FACTCHECK_TARGET_UNAVAILABLE_
  PHRASES` (новый пул, прежние пулы не тронуты): раньше пустая цель в v2
  проваливалась в Writer с пустым тезисом.

`services/smartmodule_phrases.py`: добавлен только новый класс
`FACTCHECK_TARGET_UNAVAILABLE_PHRASES` (3 честные фразы, без выдуманного
вердикта). `FACTCHECK_NO_CLAIM_PHRASES`, `FACTCHECK_CLARIFY_PHRASES` и прочие
пулы не менялись.

`services/factcheck_service.py` **не менялся**: вердикт-слой уже разделяет
`insufficient_evidence` (`factual_verdict`) и «нет тезиса»; правка не
требовалась (файл был в скоупе «только если нужно состояние cooldown/допуска»).

## 4. Этап C — дальнейший анализ не тронут

Принятый тезис идёт тем же конвейером: `resolve_claim_publication` →
`build_envelope` (attribution/dates) → планировщик `fp3` (per-part запросы) →
`check_claim_envelope` | `check_claim` → `CheckedVerdict` → renderer →
доставка. Core/Expression/Style и egress-guard не менялись; второго Writer
или второго фактчека не добавлено. Атрибуция анцедента по-прежнему берётся от
автора цитаты (`ClaimItem.author`), чужой тезис цели не приписывается.

## 5. Этап D — cooldown после раннего отказа

`handlers/factcheck.py`:

* `run_factcheck` и `_factcheck_temporal` теперь возвращают исход прогона
  (`verdict | no_claim | ambiguous | unavailable | error | busy`);
* `_settle_cooldown(chat, user, outcome)` снимает слот кулдауна **только** для
  ранних исходов (`REFUNDABLE_OUTCOMES` в оркестраторе — равенство наборов
  проверяется тестом); доставленный вердикт слот сохраняет;
* `_refund_cooldown` работает и для in-memory `CooldownTracker`, и для
  `PersistentCooldownTracker` (прод-дефолт): удаляется та же строка
  `throttle_state` со `scope='factcheck'` — **без изменения схемы БД**;
* ранние пути заранее (`пустая/нерелевантная цель`) и ошибочные пути
  (`busy`, поиск/LLM/неожиданный сбой, пустой ответ модели) тоже возвращают
  слот.

Сохранено: антиспам (после реального вердикта лимит действует), single-flight
(слот ставится до прогона, параллельный дубль получает фразу троттлинга и НЕ
запускает вторую проверку), bounded-пул смарт-модуля, защита от двойной
доставки.

## 6. Этап E — диагностика (админка/аналитика)

`_emit_admission(...)` в оркестраторе: одна `logger.info` строка
`[factcheck_admission]` + mca-событие `factcheck_admission`
(`component="factcheck.admission"`, поля в `entity_ids` JSON) со значениями:

```
target_resolved | explicit_request | claim_items_count | admission_decision |
reason_code | pipeline_path | verdict_stage | cooldown_outcome
```

`cooldown_outcome` — не константа: `_finish` передаёт `cooldown_label(outcome)`
→ `refund:<outcome>` (ранний отказ/сбой, слот будет снят) либо
`kept:<outcome>` (доставленный вердикт, лимит сохранён). Фактический результат
снятия слота пишет handler: событие `factcheck_cooldown`
(`refund:<outcome>` | `refund_failed:<outcome>` | `kept:<outcome>`) — см. §11.

Ни текстов сообщений, ни авторов, ни URL. Разделение случаев:

* ложный/честный отказ — `admission_decision=no_identifiable_claim` +
  `reason_code` (`no_claim_after_context` — без явного запроса,
  `explicit_request_no_checkable_core` — явный запрос после изучения цели и
  контекста);
* «неизвестно, что проверять» — `ambiguous_target` / `insufficient_context`;
* «цель недоступна» — `unavailable_target`;
* «тезис есть, доказательств не хватило» — `admission_decision=checkable` +
  `verdict_stage=insufficient_evidence` (вердикт-слой, не гейт).

Весь путь допуска также логируется в handler'е
(`[factcheck] suitability gate | … | reason=… | admission=… | explicit=…`).

## 7. Приёмка §5 — 8/8 детерминированных сценариев

`tests/test_evol_fc_admission.py` (18 тестов, все офлайновые: LLM/сеть/Telegram
не вызываются):

| # | Сценарий §5 | Тест | Результат |
| --- | --- | --- | --- |
| 1 | Явный `фактчек` в reply к пересланному тезису о заражении через стикер/ссылку → тезис принят, проверка запускается, не `no_claim` | `TestScenario1ForwardedClaimWithLink::test_red_reproduction_without_explicit_request` (RED: `no_claim_after_context`), `…test_explicit_request_admits_checkable_core`, `…test_pipeline_runs_and_no_claim_pool_not_used` | PASS |
| 2 | Тот же тезис разговорно, с матом/сарказмом, без дат и цифр → ядро выделяется, ключевое слово не требуется | `TestScenario2ColloquialClaim::test_no_keyword_predicate_but_core_present` (предикат молчит, ядро найдено), `…test_explicit_request_checks_colloquial_claim`, `…test_hint_with_core_is_enough_for_explicit_request` | PASS |
| 3 | Смесь факта и эмоции → проверяется фактическая часть, оценка отделяется | `TestScenario3MixedClaim::test_factual_part_checked_opinion_separated` | PASS |
| 4 | Два тезиса в одном посте → оба распознаны по действующей per-claim policy | `TestScenario4TwoClaims::test_both_claims_recognised_per_claim_policy` (2 claim_items, 2 единицы планировщика) | PASS |
| 5 | Явный `фактчек` на пустое сообщение → честный ответ о недоступной цели, без выдуманного вердикта | `TestScenario5EmptyTarget::test_handler_honest_unavailable_without_invented_verdict`, `…test_v2_stops_before_paid_search`, `…test_claim_found_in_related_material_is_checked` | PASS |
| 6 | Несколько неоднозначных соседних сообщений → уточнение, не `no_claim`, без приписывания чужого тезиса | `TestScenario6AmbiguousTarget::test_clarification_not_no_claim_and_no_foreign_claim`, `…test_v2_asks_for_clarification` | PASS |
| 7 | Тезис определён, поиск ничего надёжного не подтвердил → `insufficient_evidence`, не `no_claim` | `TestScenario7InsufficientEvidence::test_insufficient_evidence_is_not_no_claim` | PASS |
| 8 | Повтор после раннего отказа + одновременные вызовы → нет необоснованного полного cooldown, антиспам и single-flight работают | `TestScenario8CooldownAndSingleFlight::test_outcome_sets_match_orchestrator`, `…test_persistent_tracker_refund_deletes_slot`, `…test_retry_after_early_refusal_not_blocked`, `…test_single_flight_and_antispam_preserved` | PASS |

Команда: `py -3 -m pytest tests/test_evol_fc_admission.py -q` → **22 passed**
(18 базовых + 4 теста review-fix F1, см. §11).

Полный разбор review-fix F1 (§3.E: `cooldown_outcome`) — §11 в конце документа.

## 8. Регрессия

| Набор | Результат |
| --- | --- |
| `tests/ -k factcheck` | **582 passed** |
| Шесть именованных наборов §5 + новый файл: `test_factcheck_orchestrator_cfg06.py`, `test_factcheck_service.py`, `test_factcheck_gate_cfg06.py`, `test_factcheck_handlers.py`, `test_factcheck_renderer_cfg06.py`, `test_factcheck_prompts.py`, `test_evol_fc_admission.py` | **159 passed** |
| Широкий срез `-k "factcheck or phrase or orchestrator or renderer or prompt or egress or unified_core or registry or config_cache or smartmodule"` | **2209 passed, 3 failed** — те же 3 падения воспроизводятся на чистом `14b67272` (отдельный worktree): **2208 passed, 3 failed** |
| `TestAggregatorFailureTaxonomy` (ранее известные 2 падения «DDG + провайдер-каскад») | **4 passed** — на этом HEAD не воспроизводятся (исправлены `98a4254f`), мой лейн их не касается |

Актуальные прогоны после review-fix F1 — в §11 (числа этой таблицы относятся к
исходному кандидату до фикса телеметрии).

Предсуществующие падения (не связаны с лейном, воспроизводятся на базовом
HEAD):
`test_mca08_style_form.py::TestObservabilityRegistry::
test_declared_events_really_emitted_in_code` и
`test_mca17a_observability_core_round1027.py::
test_registry_event_names_exist_in_code` — оба про `mca07_answer_cache` у
`direct.reply` (не про фактчек);
`test_asap8_v6_p1_d11_registry.py::TestD11EffectiveGates::
test_env_off_beats_product_toggle` — падает только в комбинированном прогоне
(порядок/env-протечка), изолированно и на базовом HEAD — PASS.

Широкий прогон по всем файлам, импортирующим `handlers.factcheck`,
`smartmodule_phrases`, `factcheck_orchestrator|suitability` (32 файла):
**1388 passed, 1 failed (тот же pre-existing mca08), 18 errors в
`test_youtube_multimodal_download_round1024.py`** — setup-monkeypatch
`handlers.youtube.get_smart_cache`, которого больше нет в модуле (video-лейн,
вне скоупа; не мой дефект и не регрессия фактчека).

## 9. Остаточные риски и ограничения

1. **Живой Telegram не проверялся** (DoD запрещает живые публикации). Контракт
   подтверждён детерминированными тестами и регрессией; фактический прод-прогон
   фиксируется новой телеметрией `[factcheck_admission]`.
2. **Флаг гейта**: на проде `flags.factcheck_suitability_gate` мог быть включён
   вручную. При выключенном гейте дефект реплики «нечего проверять» невозможен
   по построению (маршрут `no_claim` недоступен), но v2 вызывает suitability
   напрямую — исправление действует и там.
3. `explicit_request` выводится из `kind != "auto"`; если появится новый
   автоматический вход, он обязан приходить с `kind="auto"`, иначе получит
   смягчённый допуск.
4. Ссылка-материал в проверяемые пункты не попадает (это источник, а не тезис);
   фактическое открытие ссылки остаётся в существующем retrieval/fetch-контуре.
5. Cooldown-возврат при `error` не даёт злоупотребления: софт-лимит остаётся
   для реальных вердиктов, а параллельные/дублирующие вызовы по-прежнему
   режутся слотом и пулом.
6. `explicit_request` смягчает допуск, но НЕ отменяет честные исходы: пустая
   цель, отсутствие тезиса после изучения цели/контекста, неоднозначность и
   нехватка доказательств остаются раздельными ответами (§2.4).
7. Разделение «факт проверяем / оценка остаётся оценкой» реализовано на слое
   допуска: оценочная часть не превращается в проверяемый `claim_item`
   (`claim_type=MIXED_CLAIM` сохранён). Формулировку «эта часть — оценка» в
   публичном ответе даёт существующий Writer-контракт для `mixed`; промпты —
   закоммиченный лейн и в этой задаче не менялись.

## 10. Изменённые файлы

```
handlers/factcheck.py
services/factcheck_orchestrator.py
services/factcheck_suitability.py
services/smartmodule_phrases.py
tests/test_evol_fc_admission.py        (новый, CONTRACT owner=ASAP-FC-ADMISSION-01)
plans/features/evol/audit/w7-fc-admission.md
```

Не тронуты: `web/**`, `prompt_registry`/`prompt_composer` (закоммиченные лейны),
video/social-файлы, схема БД (новых таблиц нет), `services/factcheck_service.py`.

## §11. review-fix F1 — `cooldown_outcome` был мёртвым полем

**Находка Reviewer.** В admission-телеметрии `cooldown_outcome` всегда
равнялся дефолту `not_applicable`: `_emit_admission(...)` вызывался без этого
аргумента, `_settle_cooldown`/`_refund_cooldown` (handlers/factcheck.py)
писали generic `outcome=early_refusal`, а случай «слот сохранён» не писался
вообще. §3.E требует измерять `cooldown_outcome` — отчёт заявлял поле, но
наблюдаемого значения не было.

**Причина.** Поле допуска эмитится в оркестраторе ДО расчёта кулдауна
(handler ставит/снимает слот после возврата `run_factcheck`), поэтому никакой
фактический исход туда не попадал, а собственного события кулдауна не было.

**Исправление (минимальное, без новых текстов/авторов/ссылок и без изменения
семантики снятия слота):**

* `services/factcheck_orchestrator.py::cooldown_label(outcome)` — единый
  словарь меток: `refund:<outcome>` для `REFUNDABLE_OUTCOMES`,
  `kept:<outcome>` для остальных. `_finish` передаёт её в единственный вызов
  `_emit_admission`, поэтому в admission-событии теперь реальное значение
  (`refund:unavailable`, `kept:verdict`), а не константа.
* `handlers/factcheck.py::_settle_cooldown` теперь **возвращает** фактическую
  метку и пишет её: `refund:<outcome>` (слот снят), `refund_failed:<outcome>`
  (снятие не удалось — fail-open, лимит остался), `kept:<outcome>` (слот
  сохранён после доставленного вердикта). `_refund_cooldown` логирует
  конкретный `outcome=` вместо `early_refusal`.
* Новое короткое событие `factcheck_cooldown`
  (`component="factcheck.cooldown"`, `entity_ids={"cooldown_outcome": ...,
  "run_outcome": ...}`) + одна INFO-строка `[factcheck_cooldown]` — по одному
  событию на прогон, обе ветки (раньше «kept» не писался). Логика допуска
  осталась одна, семантика возврата слота не менялась.

**Тесты (4 новых, всё офлайн):**

| Тест | Что доказывает |
| --- | --- |
| `TestScenario8CooldownAndSingleFlight::test_settle_cooldown_reports_actual_outcome` | обе ветки фактического значения: `refund:no_claim` (слот снят) и `kept:verdict` (слот сохранён); метка есть в логе и в `entity_ids` mca-события, набор полей события — только `cooldown_outcome`/`run_outcome` |
| `…test_settle_cooldown_reports_refund_failure` | fail-open снятия слота честно виден как `refund_failed:error` (не притворяется возвратом) |
| `…test_cooldown_label_vocabulary_matches_orchestrator` | словарь меток handler'а и оркестратора совпадает |
| `…test_admission_event_carries_non_default_cooldown_outcome` | в `[factcheck_admission]` реальное `cooldown=refund:unavailable`, строки `not_applicable` больше нет; `test_claim_found_in_related_material_is_checked` дополнительно закрепляет `cooldown=kept:verdict` на вердикт-ветке |

**Проверки после фикса (текущий кандидат `fcdc69a8` + незакоммиченные правки
лейна):**

| Набор | Результат |
| --- | --- |
| `tests/test_evol_fc_admission.py` | **22 passed** |
| шесть именованных наборов фактчека + новый файл (`test_factcheck_orchestrator_cfg06`, `test_factcheck_service`, `test_factcheck_gate_cfg06`, `test_factcheck_handlers`, `test_factcheck_renderer_cfg06`, `test_factcheck_prompts`, `test_evol_fc_admission`) | **163 passed** |
| `tests -k factcheck` | **584 passed, 1 failed** — единственное падение `tests/test_evol_vision_sync_core.py::test_sc17_factcheck_pending_forbids_no_claim`: это новый untracked тест параллельного Vision-лейна, который правится в этом же worktree в те же минуты (вместе с `services/media_readiness.py`, `mca_vision.py`, `factcheck_service.py`); на базовом `fcdc69a8` файла не существует |

Контрольная сверка с базой `fcdc69a8` в отдельном worktree: `-k "factcheck or
orchestrator or smartmodule or suitability"` даёт **792 passed** (без моих
изменений) — то есть фактчековые наборы не регрессировали; известные падения
`test_declared_events_really_emitted_in_code` и
`test_registry_event_names_exist_in_code` воспроизводятся и на базе (оба про
`mca07_answer_cache` у `direct.reply`, к фактчеку и к новому событию
`factcheck_cooldown` отношения не имеют — новое имя события не объявлено в
реестре процессов, а реестр проверяется только в обратную сторону).
