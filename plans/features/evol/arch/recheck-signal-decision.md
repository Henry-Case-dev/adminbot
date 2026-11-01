# Решение: сигнал «проверь заново» и отмена reuse (ASAP-EVIDENCE-ROUTING-01 v3)
Статус: `ARCHITECT_DECISION` — закрывает открытый вопрос Builder по строке §3.3 контракта.
База: `plans/features/evol/arch/evidence-routing-contract.md` §1.2 п.2, §1.3, §1.6, §3.1, §3.3.
Код: worktree `evol-71536a366a11-c63f6f44`, ветка `evol/impl`. Внешние источники не использовались.
## 1. Вердикт
**Выбран вариант (г): optional-поле плана L1 `recheck: true`.** Вариант (б) в коде **уже реализован**
и сам по себе пробел не закрывает; вариант (в) отклонён. Одновременно решается смежный вопрос:
**явная ссылка (URL) в реплике обязана читаться заново**, если переиспользуемая запись указывает на
другой источник (§4).
## 2. Почему существующих детекторов не хватает (наблюдение)
`_evidence_explicit_request` (`services/direct_chat_service.py:2415–2453`) уже поднимает
`verify=True` из `direct_capabilities.detect_action_intent` при `INTENT_FACT_CHECK`, т.е. «один
существующий маркер как класс „проверь факт“» уже работает. Прогон на текущем HEAD: «правда ли,
что … вышел» / «проверь факт: …» / «проверь это» → `fact_check` (+ referential `True` у последней);
«проверь заново», «обнови данные про», «перепроверь», «проверь ещё раз», «актуальна ли инфа про»,
«свежие данные про» → intent `""` и referential `False` у всех шести. Причина структурная:
`_FACTCHECK_MARKERS` (`services/direct_capabilities.py:288–291`) — восемь фиксированных подстрок
через `_has_stem` (`:347–357`), а `is_referential_claim` (`services/temporal_factcheck.py:103–131`)
требует референтной формы, отсутствия «что» и ≤80 символов. Класса «источник уже прочитан, но
человек требует свежести» нет ни в одном детекторе.
Второй тупик: L1 не может выразить это через `capabilities_needed=["web_search"]` — при reuse
политика даёт `QUALIFIED_VERIFIED_REUSE` (`services/evidence_policy.py:707–718`), а
`_l1_tool_subset` тогда вырезает сетевые evidence-инструменты даже из L1-запрошенных
(`services/direct_chat_service.py:5998–6011`). Значит нужен отдельный смысловой признак в том же
единственном L1-вызове — прецедент §1.6 (`future_intent`, `services/direct_l1.py:141–155`;
`external_claims`, `:228–234`, `:551–555`).
## 3. Отклонённые варианты
- **(а) расширить `_FACTCHECK_MARKERS`** — запрещено §1.3. Практически это не одна строка: нужны
  словоформы («проверь/проверить/проверьте/перепроверь»), отрицания («не надо проверять»),
  различение шутки/цитаты («он написал: перепроверь») — неограниченный растущий словарь, ровно
  запрещённый класс; плюс ложные срабатывания дают шторм лишних fetch'ей.
- **(б) один существующий маркер как класс** — сделано (§2), закрывает 3 из 9 формулировок; как
  самостоятельное решение неполно, остаётся частью итогового поведения.
- **(в) сузить §3.3 до референтных claim'ов** — тихое ослабление требования владельца (§1.2 п.2
  «независимо от confidence/tool_policy/mode» + §3.3 «явная просьба → bypass, тестируется») и
  воспроизведение дефекта `silent staleness` из ревью
  (`plans/features/evol/reports/w13-evidence-routing-review-waves3-5.md`, BLOCKER-2).
## 4. Смежный вопрос: явная ссылка при уже покрытом claim
Reuse проверяется в правиле 6 (`services/evidence_policy.py:707–718`) раньше, чем учитывается
`supplied.urls`; URL влияет лишь на набор capabilities (`:591–596`), поэтому ответ строится по
ранее прочитанному **другому** источнику, а присланный URL не читается.
**Решение: явная ссылка форсирует чтение этого адреса, кроме одного случая** — запись reuse
указывает на **тот же** URL, свежая (TTL), не `contested`, выдержка доставлена
(`services/source_reuse.py:410–452`, `:476–498`); тогда это буквально тот же документ. Это не новое
требование, а применение §3.1/§3.3: переиспользуется прочитанный **источник**, и ответ по другому
адресу, чем названный человеком, — подмена доказательства. Механизм минимальный, в интеграционном
слое (политика остаётся чистой): `_evidence_reuse_claims(..., supplied_urls=urls)` игнорирует
запись, чей `record.url` не входит в `urls` (пустой `record.url` при присланных ссылках — тоже
игнор: асимметрия в сторону проверки). Побочно `required_caps` станет
`("fetch_url","web_search")` (`:591–596`) и адрес реально читается.
## 5. Точная дельта для Builder (один проход)
1. `services/direct_l1.py`: `L1Plan.recheck: bool = False` (`:192–234`, рядом с `external_claims`);
   в `normalize_l1_plan` — `plan.recheck = data.get("recheck") is True` (строгий boolean по
   прецеденту `needs_clarification`, `:535`; `"true"`, `1`, `null`, отсутствие → `False`).
2. `services/evidence_policy.py`: `ExplicitRequest.recheck: bool = False` и входит в `any`
   (`:310–326`); перед правилом 2 при `runtime_state.initiative` — `replace(explicit, recheck=False)`
   (в инициативе нет просьбы человека); правило 2 (`:647–661`) — `note="plan_recheck"` (приоритет
   note: `read_source` → `verify` → `search` → `recheck`); `_required_caps_for` (`:580–597`) —
   `recheck` идёт веткой `search` (`("fetch_url","web_search")` при `supplied.urls`, иначе
   `("web_search",)`), без `fact_check` (§2.4). `recheck` не создаёт и не снимает `skip_reason` и не
   понижает `required`.
3. `services/direct_chat_service.py`: `_evidence_explicit_request(query, reply_text="", plan=None, *)`
   — `recheck` из `getattr(plan,"recheck",False)`, вызов в preflight (`:5536`) получает `plan`;
   bypass (`:5540–5541`) — `bool(explicit.verify or explicit.recheck)`; `_evidence_reuse_claims`
   (`:2482–2507`) получает `supplied_urls=()`, отбрасывает запись с чужим `url`; `urls` прокинуть
   из preflight (`:5535`).
4. `services/chat_prompts.py`: расширить **ту же невыпущенную** ревизию
   `_DIRECT_L1_EXTERNAL_CLAIMS_EVR1` (`:1314–1321`): `"recheck": false` в JSON-схему существующим
   `.replace(...)` (`:1330–1336`) и один абзац — `recheck` ставится, только если человек просит
   проверить заново / освежить / уточняет актуальность / сомневается в актуальности сказанного;
   `recheck` не отменяет проверку и не заменяет `external_claims`, а запрещает переиспользовать
   ранее прочитанный источник; для шутки, цитаты, пересказа и обычного вопроса о факте — `false`.
   Без перечисления фраз и без квот символов.
5. `services/prompt_migrations.py` — **не менять**: ступень ссылается на живой канон (`:530–534`),
   `PREV_DIRECT_L1_PLANNER_EVR0` остаётся целью отката; новая ступень не нужна, т.к. EVR1 не выпущен
   (прод 2.58.146 его не содержит). `services/prompt_registry.py`: пересчитать
   `FACTORY_SET_SHA256_12` (`:2690`) через `factory_set_fingerprint()` (`:2305`), обновить комментарий.
6. Обновить литералы реконструкции канона: `tests/test_direct_l1_l1d_contract.py:69–73`,
   `tests/test_direct_l1_corrective_r1.py:93–98`, `tests/test_asap_speech_r3b_canon.py:164–171`,
   `tests/test_post_asap5_w2_tech_reasoning.py:269`, `tests/test_post_asap5_w1_writer_core.py:256`,
   `tests/test_p0_prompts_core.py:115` (новый отпечаток).
Порядок в ходе не меняется: bypass reuse ⇒ правило 2 (`required=True`) ⇒ `_l1_tool_subset` не
вырезает evidence-инструменты (снятие только при `QUALIFIED_VERIFIED_REUSE`, `:6007–6011`).
## 6. Обязательные тесты (в `tests/test_evol_evidence_routing.py`; хелперы `_service`, `_reuse_plan`,
`_seed_reuse`, `_permissive_context`, `_reuse_turn`)
1. `test_wave6_plan_recheck_cancels_reuse` — свежая доставленная запись + `recheck=True`:
   `required is True`, `note == "plan_recheck"`, `web_search` в caps, `_evidence_reuse_pack is None`,
   запись удалена (повторный `_evidence_reuse_claims` пуст).
2. `test_wave6_recheck_keeps_evidence_tools_announced` — `_l1_tool_subset(..., decision)` возвращает
   схемы с `web_search`/`fetch_article` (доказательство на tool-шве, не только флаг).
3. `test_wave6_recheck_not_downgraded_by_confidence_or_mode` — `recheck=True` + `confidence=0.0`
   (`low`) + `execution_mode="none"` + пустой `capabilities_needed` → `required` True.
4. `test_wave6_plain_question_still_reuses` (негатив, анти-шторм) — без `recheck` тот же ход даёт
   `QUALIFIED_VERIFIED_REUSE` и reuse-пакет.
5. `test_wave6_joke_mentioning_check_does_not_refetch` (негатив) — «проверь, как я тебя дразню, это
   было смешно»: `_evidence_explicit_request(...).any is False`, при свежей записи reuse сохранён,
   `note != "plan_recheck"`.
6. `test_wave6_recheck_parse_is_strict_boolean` — `true`→True; `"true"`, `1`, `null`, отсутствие→False.
7. `test_wave6_initiative_ignores_recheck` — `initiative=True` + `recheck=True` + покрытый claim →
   reuse сохранён.
8. `test_wave6_prompt_canon_has_recheck_field` — в каноне есть `"recheck": false` и фраза, что
   `recheck` не отменяет обязательную проверку; в секции нет «»/— (как в
   `test_wave5_l1_planner_informs_model_about_external_claims`).
9. `test_wave6_no_new_vocabulary` — `_FACTCHECK_MARKERS`/`_SEARCH_MARKERS`
   (`services/direct_capabilities.py:286–291`) побайтно равны текущим кортежам (страховка §1.3).
10. `test_wave6_pasted_url_forces_read_of_that_url` (запись под `https://a.example/…`, в реплике
    `https://b.example/…` → reuse не засчитан, `fetch_url` в caps, пакета нет) и
    `test_wave6_pasted_url_same_as_record_reuses` (URL совпал, свежо и доставлено → reuse сохранён).
Наблюдаемость: `note="plan_recheck"` уезжает в существующее `EVIDENCE_POLICY_DECIDED`
(`evidence_policy.py:435–456`). Новых `reason_code`, событий, полей БД, модулей и kill-switch нет
(policy OFF → `recheck` не действует, честный паритет).
## 7. Что решение НЕ исправляет
- Деградированный план (`source="fallback"`, `evidence_policy.py:745–755`) не несёт `recheck`:
  «перепроверь …» при сбое планировщика по-прежнему не вызывает чтения (отдельная семантика
  fallback, здесь не меняется).
- Если L1 не поставит `recheck` на необычной формулировке, поведение остаётся сегодняшним
  (`QUALIFIED_VERIFIED_REUSE`): гарантия «любая русская формулировка» без словарей недостижима и
  контрактом не обещана; покрытые маркерами формы по-прежнему закрывает (б).
- Пользовательский канон L1 без новой фразы → поле не ставится: деградация до текущего поведения,
  не поломка. Локальное чтение кода («проверь в исходниках») остаётся `CAPABILITY_NOT_READY`
  (`EVOL-SRC-READER`).
## 8. Риск, откат, параллельность
Риск **R1**: ложное `recheck=True` → максимум один адресный lookup под `allowed()` (флаги/квота/
SSRF) и §2.3; ложное `False` → не хуже текущего. Откат: ревизия EVR1 не выпущена,
`PREV_DIRECT_L1_PLANNER_EVR0` = прод-байты, ступень лестницы уже существует; ручные редакции
владельца `known_canon_hashes` не перезаписывает. Параллельность — `SERIALIZE`: один writer на
`direct_l1.py` + `evidence_policy.py` + `direct_chat_service.py` + `chat_prompts.py` +
`prompt_registry.py` + перечисленные тесты (канон и отпечаток общие).
## 9. Вопрос владельцу
**Не требуется.** Продуктовый выбор уже сделан контрактом (§1.2 п.2, §3.3); вариант (в) означал бы
отмену его требования, а не выбор между вариантами. Решение принимается технически.
