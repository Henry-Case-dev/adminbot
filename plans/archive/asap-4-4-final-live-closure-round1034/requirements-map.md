# ASAP 4.4 — requirements-map.md

Feature: `asap-4-4-final-live-closure` — FINAL production closure: Cover Style + Hybrid Summary + GraphRAG.
SoT: `plans/current_task.md:26365–27146` (§0–§12, НЕ изменяется). Runtime-код — истина для root cause; старые `Approved`/отчёты не используются (26369–26373).
Pass **заменяет closure ASAP 4.3**; возврат к MCA **приостановлен** до успешного deploy + live acceptance (26375–26376).
Порядок: Step 0 (pre-fix repro) → зоны Z1–Z6 (Builder) → Z7 focused tests → Z8 real E2E → Z9 Reviewer → Z10 deploy + live A/B → Z11 отчёт/архив/MCA.
Дисциплина: live evidence > unit/mock; focused tests, не full suite; forbidden list §11 соблюдается (см. §11 ниже). ADR не создаются: реального архитектурного противоречия не найдено (проверено на планировании).
Верифицировано: DoD = **23 пункта** (27085–27107); §6 = **24 focused-теста** (13 cover + 5 L2 + 6 GraphRAG).

## Root-cause status (на 05.10.2026)

| Root cause | Статус | Доказательство / якоря | Задача |
|---|---|---|---|
| RC-A base preview создан, но не зарегистрирован как DB asset | ✅ **FIXED + DEPLOYED 2.58.51** (feat `acbbe1f`; delta review Approved `1c11336`; negative control RED воспроизведён) | `services/cover_style_preview.py:474–490` — `_store_base` → `registry.upsert_asset` на обоих call sites (`:364`, `:382`), failure → job failed ДО styled/pair write; prod health 200, ff `2329a9d..1c11336`, PID 3610541, 62+62 focused passed | — (live proof: Canary A repeat 4.3 идёт сейчас, `04e615d` → пометить «live proof pending/attached» до факта; T-4867/T-4887) |
| RC-B counter semantics: UI «Следующий номер» = `counter_value`=11, prod increment RETURNING → 12 | 🔴 OPEN | `services/cover_style_registry.py:560–565` (`counter_value+1 RETURNING` = last assigned); `web/index.html:810–813` (label «Следующий номер» на `counter_value`); live log `issue_number=12` | T-4868 |
| RC-C Test Style рисует «ВЫПУСК 00» | 🔴 OPEN | `services/cover_style_registry.py:596–598` (`preview_issue_display` жёстко issue=0, zero-pad 2) | T-4869 |
| RC-D Test Style тестирует сохранённый DB-профиль, не draft UI | 🔴 OPEN | `web/api/cover_styles.py:1038–1043` (`TestStyleBody` = только `profile_id` + legacy upload), `:1076` заново читает профиль из DB | T-4870 |
| RC-E любой `upsert_profile` UPDATE bump `revision` → no-op Save делает pair stale | 🔴 OPEN | `services/cover_style_registry.py:255–305` (revision+1 на UPDATE), `:391` (`preview_pair_current` требует `preview_revision == revision`) | T-4871, T-4872 |
| §2 prompt capability: UI «неизвестно» vs provider `400 prompt too long`; без числа → generic `bad_request` | 🔴 OPEN | `web/api/cover_styles.py:266–345` (sync `_budget`/`_prompt_limit_state`/`jobs_public_capabilities`); `services/cover_style_pipeline.py:199–260` (`_edit_capabilities_for`, `resolve_style_slot_inherited`); `services/cover_style_jobs.py:1224/1370/1514`; `services/image_capabilities.py:562` (`VERIFIED_PROMPT_LIMIT_REGISTRY`; `learned_safe_ceiling`/`prompt_limit_unknown` отсутствуют); `services/cover_style_edit.py:463–483` (400 без числа → `bad_request`) | T-4873–T-4875 |
| §4 L2 → Legacy после 2 failed targeted revision; stale `_deterministic_findings` `[L-ASAP4-D5]` OPEN | 🔴 OPEN | `services/summary_l2_review.py:870` (расчёт один раз до loop), `:896` (передаётся Reviewer каждую итерацию), `:1150` (def); archived review `asap-4-embedding-graphrag-cover-runtime-round1030/review.md:212,304` | T-4876, T-4877 |
| §5 GraphRAG cooldown storm: ~2 embed-attempt/fact + stacktrace spam; quota groups не управляются | 🔴 OPEN | `services/summary_memory.py:2544` (`_memorize_facts_inner`), `:2734–2737` (vector может быть None → повторный вызов), `:2921–2934` (`_save_graph_fact_embedding` снова `_embed` + WARN `exc_info=True`); `services/embedding_control_plane.py:16–17/206/266–268` (hot-ключ есть, UI нет) | T-4878–T-4880 |

Cross-pass (workflow_state.md NOTE 10, 05.10.2026): активный 4.3-canary агент (Canary A repeat → override → Canary B) — его результат и побочки аудируются в **T-4867**; manual 800 override (если выставлен) **снять** — §11 запрещает blind-800 перенос на Pro; counter нормализовать в next=11 до 4.4-приёмки; случайная публикация документируется. Результат 4.3 Canary A repeat может быть приложен как live-доказательство RC-A (без повторного прогона).

## §0 — Цель (26380–26393)

| # | Требование | Критерий | Task |
|---|---|---|---|
| 0.1 | Карточка `До` больше не пустая | before-ассет registered + GET=200 + виден в UI | T-4887 (live), T-4884 (E2E), T-4881#1–3 |
| 0.2 | Test Style показывает ВЫПУСК 11, а не 00 | display = current next_issue_number, counter не меняется | T-4869, T-4881#4 |
| 0.3 | Production run получает 11, не 12 | next_issue_number contract + atomic allocate 11 | T-4868, T-4881#5 |
| 0.4 | После «Сохранить стиль» pair не исчезает | no-op save не bump revision; reopen видит ту же pair | T-4871, T-4872, T-4881#7–10 |
| 0.5 | Лимит не «неизвестно», 400 без числа не generic | единый resolver + `prompt_limit_unknown` + ≤1 retry | T-4873–T-4875, T-4881#11–13 |
| 0.6 | Summary не уходит в Legacy после 2 revision | stale findings устранены; причина диагностируема | T-4876, T-4877, T-4882 |
| 0.7 | GraphRAG не спамит cooldown/stacktrace | batch breaker + 1 WARN + управляемые quota groups | T-4878–T-4880, T-4883 |
| 0.8 | Закрытие только после live A/B | Canary A/B на проде, mock не засчитывается | T-4887, T-4888, T-4889 |

## §1 — Root cause confirmation (26397–26627)

| RC | Проверка на текущем кандидате | Критерий | Task |
|---|---|---|---|
| RC-A (26403–26445) | Подтвердить, что fix в архиве/кандидате: `_store_base` → `upsert_asset` оба call sites; failure → job fail до pair write | Fix присутствует; приложить live Canary A repeat; новый E2E RED на pre-fix коде | T-4866, T-4867, T-4884 |
| RC-B (26449–26502) | Воспроизвести: UI next=11 → increment → 12 | Repro записан в evidence.md (log/SQL/file:line) | T-4866 |
| RC-C (26505–26530) | Воспроизвести: Test Style отдаёт `00` при next=11 | Repro записан; Test Style не расходует counter | T-4866 |
| RC-D (26534–26569) | Воспроизвести: draft изменён → Test Style тестирует старую DB-версию | Repro записан (payload `{profile_id}` → DB read) | T-4866 |
| RC-E (26573–26625) | Воспроизвести: no-op Save → revision+1 → pair stale → placeholders | Repro записан (revision N→N+1) | T-4866 |
| §2/§4/§5 | Подтвердить контрактные разрывы (resolver split, stale findings, double embed) | Чеклист подтверждено/опровергнуто с file:line; при расхождении — стоп к Архитектору (ожидаемо: нет) | T-4866 |

## §2 — Prompt capability: один runtime truth (26629–26738)

| Требование | Критерий | Task | Reuse/notes |
|---|---|---|---|
| Один async resolver effective style-edit capability для UI meta, budget, Test Style, production, diagnostics/Inspector | Все пути вызывают один resolver; результат совпадает | T-4873 | `resolve_style_slot_inherited` (`cover_style_pipeline.py:210`) + `jobs` final inherited slot (`cover_style_jobs.py:1224`) — свести к одному async API |
| Capability key = provider + normalized base_url + model + resolved route + operation | Ключ нормализован; кэш/запись per key | T-4873 | `image_capabilities.py` precedence уже есть |
| Source taxonomy: `published_exact` / `runtime_exact` / `manual` / `learned_safe_ceiling` / `unknown`; UI не пишет «неизвестно», если есть доказанная информация | Source виден в UI/meta; learned ceiling НЕ выдаётся за exact max | T-4874 | `VERIFIED_PROMPT_LIMIT_REGISTRY` (`:562`) расширить source-полем |
| Не переносить 800 на `qwen-image-3-pro` без отдельного metadata/source; live 400 = «too long», не точный N | Нет hardcode 800 из публичного Qwen Image 3 route | T-4874 | §11 запрещает blind-800 |
| 400 «too long» без числа → semantic `prompt_limit_unknown`, не generic `bad_request`; ≤1 bounded adaptive retry; retry реально короче; P0/P1 invariants (один PERMsoc, верный issue number, Medved Press/logo/reference roles, comic/graphic-novel, запрет дублей); ≤1 дополнительный paid edit; успех → `runtime_safe` ceiling; повторный fail → `prompt_limit_unknown_after_retry` | Классификация + retry policy + ceiling source протестированы; нет скрытого multi-paid loop | T-4875 | `cover_style_edit.py:463–483`; compile `cover_style_jobs.py:1021/1370/1514` |
| Manual override — высший приоритет | Manual побеждает; сохраняется | T-4874 | 4.3 §7.2 persistence reuse |

## §3 — Production cover acceptance (26742–26790)

| Требование | Критерий | Task |
|---|---|---|
| Canary A `[REAL]` (26746–26772): next=11 перед стартом; быстрый start; durable job completed; base реально сгенерирована; before id в DB registry; GET before = 200 + image; styled asset; GET after = 200 + image; UI одновременно before+after; `ВЫПУСК 11` (не 00); Test Style не меняет next number; editor показывает effective provider/model + usable capability; нет `Failed to fetch`; нет generic `bad_request` из prompt-too-long; Save без изменений не уничтожает pair; закрыть/открыть editor → та же pair | Весь список подтверждён на проде; job id в evidence | T-4887 (live), T-4881, T-4884 |
| Canary B `[REAL]` (26774–26790): production run issue 11; retry того же run 11; published cover outcome = `styled`; `base_fallback` НЕ успех Style; следующий независимый = 12; analytics/Inspector показывает фактические provider/model/route, compiled length, capability source, styled outcome | Run id + номера 11/11/12 + `styled` в evidence | T-4888 (live), T-4868, T-4881#5, T-4882 |

## §4 — Hybrid Summary: L2 → Legacy (26794–26865)

| Требование | Критерий | Task |
|---|---|---|
| Rejection наблюдаем: stage event c `review_attempt`, `verdict`, `finding_codes[]`, `blocking_count`, `paragraph_ids[]`, `revision_target`, `revision_result`, `revision_failure_reason`, `deterministic_validation_codes[]`; без raw text/prompt/секретов | Событие есть; по live-логу можно назвать причину | T-4877 |
| Реальный corrective pass воспроизводит один run и называет конкретную причину (не «увеличить budgets/retries»); разобрать `apply_targeted_revision` / anchor-source binding / schema / evidence refs / reason из `SUMMARY_REVISION_RESULT`; `MAX_REVISIONS` не увеличивать; Reviewer strictness/evidence fail-closed не ослаблять | Причина названа + pre/post repro; `needs_fixes` не превращён в auto-Approved | T-4877 |
| Stale `_deterministic_findings` (L-ASAP4-D5): после каждой успешной revision findings/validator context соответствуют текущему документу; regression: finding present → revision исправила → next review не получает stale finding | Regression-тест зелёный; повторное ревью без stale | T-4876 |

## §5 — GraphRAG: cooldown storm + quota groups (26868–26975)

| Требование | Критерий | Task |
|---|---|---|
| 5.1 Batch circuit breaker: control-plane serviceability exceptions (`EmbeddingGroupCoolingDown`, `EmbeddingBudgetExhausted`, terminal pool unavailable) → `embedding_unavailable_for_batch=true` после первого доказанного состояния; остальные факты batch сохраняются text-only; dedup safe fallback без vector; `_save_graph_fact_embedding` не делает повторную network-попытку в этом batch; новая попытка только в следующем logical batch/run после recheck | ≤1 network embed-attempt цепочки на batch; все факты сохранены text-only | T-4878 |
| 5.2 Logging: 1 concise WARN/event на batch (`chat/run`, `quota_group`, `state`, `next_allowed_at`, `facts_text_only=N`, `dedup_vector_skipped=N`); без stacktrace на каждый факт; unexpected exception — со stacktrace | N фактов → 1 event; иначе unexpected не маскируются | T-4879 |
| 5.3 Quota group config в Embeddings-группе MiniApp: `primary:<group>` / `fallback_1:<group>` / `fallback_2:<group>` или structured equivalent; правило «все 3 ключа одного billing project → одна group; независимость НЕ выводить из secret key»; Analytics/Status: `keys: 3`, `groups: 1/2/3`, `rotation: none|grouped`, blocked groups, `next_allowed_at` — без секретов | UI сохраняет labels; analytics показывает топологию без секретов | T-4880 |
| 5.4 SmartModule: `graph_facts_vec`/`smart_archive` при unavailable embeddings работают FTS-only; одинаковый fingerprint + known unavailable service не спамит WARN; одна degraded state + recovery transition | Одна degraded state + recovery; WARN не на каждом факте/цикле | T-4879 |

## §6 — Focused tests (26978–27015) — 24 пункта

### Cover (26984–26998)

| # | Тест | Task | Notes |
|---|---|---|---|
| 1 | generated preview base проходит `upsert_asset` | T-4881 | RC-A: reuse delta-тест 2.58.51; pre-fix RED |
| 2 | before/after оба fetchable через реальный API route | T-4881 | + E2E T-4884 |
| 3 | failure base registry → pair не записана | T-4881 | reuse 2.58.51 negative control |
| 4 | UI next=11 → Test Style issue=11, DB counter unchanged | T-4881 | RC-C, RC-B |
| 5 | production first=11, retry=11, next run=12 | T-4881 | RC-B contract |
| 6 | Test Style использует current draft snapshot | T-4881 | RC-D |
| 7 | no-op Save не bump revision | T-4881 | RC-E |
| 8 | no-op Save сохраняет preview pair | T-4881 | RC-E |
| 9 | rendering-affecting Save инвалидирует старую pair | T-4881 | RC-E |
| 10 | exact tested draft save сохраняет/promote pair provenance | T-4881 | RC-E promote |
| 11 | UI/backend effective capability route совпадают | T-4881 | §2 resolver |
| 12 | prompt-too-long без числа → `prompt_limit_unknown` + ≤1 shorter retry | T-4881 | §2 |
| 13 | successful adaptive retry сохраняет `runtime_safe` ceiling, не выдаёт за exact max | T-4881 | §2 |

### L2 (27000–27006)

| # | Тест | Task |
|---|---|---|
| 14 | deterministic findings пересчитываются после revision | T-4882 |
| 15 | stale finding не возвращается после исправления | T-4882 |
| 16 | targeted revision invalid reason попадает в stage diagnostics | T-4882 |
| 17 | bounded cycle остаётся bounded | T-4882 |
| 18 | Reviewer strictness/evidence fail-closed не ослаблены | T-4882 |

### GraphRAG (27008–27015)

| # | Тест | Task |
|---|---|---|
| 19 | cooldown на первом факте → ≤1 network embed-attempt на logical batch | T-4883 |
| 20 | все факты сохраняются text-only | T-4883 |
| 21 | один concise WARN/event, не N stacktraces | T-4883 |
| 22 | следующий batch после recovery снова может embed | T-4883 |
| 23 | quota-group labels корректно разделяют реально независимые группы | T-4883 |
| 24 | unknown groups остаются одной safe group | T-4883 |

## §7 — Browser/E2E (27019–27038)

| Требование | Критерий | Task |
|---|---|---|
| Минимум один real backend path: worker/job → managed asset store → PG asset registry → public status → authenticated GET before → authenticated GET after → Save → reload editor | Цепочка пройдена на реальном стеке (не mock-only Playwright); RC-A обязан RED на старом коде | T-4884 |
| Mobile geometry ASAP 4.3 не перепроверять полностью, если файлы не затронуты | Проверка только при касании geometry-файлов | T-4884 |

## §8 — Reviewer (27042–27057)

| Требование | Критерий | Task |
|---|---|---|
| Один independent pass; ответить: (а) почему 4.3 тесты не поймали RC-A/RC-E; (б) новый тест RED на pre-fix или эквивалентно доказан; (в) counter semantics едины UI/API/DB/production; (г) Test Style не расходует номер; (д) prompt-limit fallback не скрытый multi-paid loop; (е) L2 Reviewer не ослаблен; (ж) GraphRAG cooldown не маскирует unexpected exceptions; (з) никаких unrelated MCA changes | Verdict + ответы по пунктам в review.md; blocking → **один** bounded Builder rework | T-4885 |

## §9 — Deploy + обязательный live acceptance (27061–27076)

| Требование | Критерий | Task |
|---|---|---|
| deploy exact candidate; health; Canary A; Save/reopen editor; Canary B; Run Inspector/логи только по этим run/job IDs; GraphRAG controlled repro; нет warning storm | Всё выполнено на проде DevOps/Orchestrator | T-4886–T-4889 |
| Нельзя закрывать с `PENDING OWNER`, если prod credentials и UI доступны; manual owner click — только как конкретный Human Gate с одной короткой инструкцией, затем продолжить тот же task без архивации | Закрытие без отложенных live-гейтов; `[PENDING OWNER]` по умолчанию не используется | T-4887–T-4890 |

## §10 — DoD checklist (27085–27107, 23 пункта, проверено)

- [ ] **D1** Test Style: real before asset виден и GET=200 — T-4887 / T-4884 / T-4881#1–3
- [ ] **D2** Test Style: real after asset виден и GET=200 — T-4887 / T-4884 / T-4881#2
- [ ] **D3** before/after относятся к одному successful job — T-4887 / T-4884 / T-4881#2
- [ ] **D4** next number 11 отображается как ВЫПУСК 11 — T-4869 / T-4881#4 / T-4887
- [ ] **D5** Test Style не расходует counter — T-4868 / T-4869 / T-4881#4 / T-4887
- [ ] **D6** production first issue = 11 — T-4868 / T-4881#5 / T-4888
- [ ] **D7** retry same run = 11 — T-4868 / T-4881#5 / T-4888
- [ ] **D8** next independent issue = 12 — T-4868 / T-4881#5 / T-4888
- [ ] **D9** Test Style тестирует текущий editor draft — T-4870 / T-4881#6 / T-4887
- [ ] **D10** no-op Save не инвалидирует preview — T-4871 / T-4881#7–8 / T-4887
- [ ] **D11** reopen editor сохраняет real preview pair — T-4872 / T-4884 / T-4881#10 / T-4887
- [ ] **D12** реальное изменение style делает old preview stale честно — T-4871 / T-4881#9
- [ ] **D13** UI и runtime используют один effective style slot/capability — T-4873 / T-4874 / T-4881#11
- [ ] **D14** prompt-too-long без N больше не generic bad_request — T-4875 / T-4881#12
- [ ] **D15** unknown-limit путь имеет ≤1 semantic shorter retry — T-4875 / T-4881#12–13
- [ ] **D16** published production cover outcome = styled, не base_fallback — T-4888
- [ ] **D17** L2 targeted-revision failure имеет точную диагностируемую причину — T-4877 / T-4882#16
- [ ] **D18** stale deterministic findings после revision устранены — T-4876 / T-4882#14–15
- [ ] **D19** real Summary не уходит в Legacy из-за исправленного stale/invalid revision mechanism — T-4876 / T-4877 / T-4882#17–18 / T-4888
- [ ] **D20** GraphRAG не повторяет известный cooldown на каждый fact — T-4878 / T-4883#19–20 / T-4889
- [ ] **D21** GraphRAG сохраняет text facts fail-soft — T-4878 / T-4883#20 / T-4889
- [ ] **D22** quota-group topology видна и настраиваема без чтения секретов — T-4880 / T-4883#23–24 / T-4889
- [ ] **D23** один live Summary показывает Hybrid + styled cover, либо remaining fallback имеет НОВУЮ, конкретную и доказанную причину — T-4888 (+ T-4890)

D23: fallback не «допустим всегда» — fallback из-за дефекта этой задачи чинить до success (27110–27111).

## §11 — Запрещено (27115–27127)

| Запрет | Как соблюдаем |
|---|---|
| Готовность без live A/B; canary на моках | T-4887–T-4889 `[REAL]`; закрытие только после прохождения |
| Увеличение timeout/retry count вместо root cause | T-4877: назвать причину; `MAX_REVISIONS` не трогать |
| Hardcode universal `800`; `runtime_safe` как exact limit | T-4874/T-4875: taxonomy + отдельный source |
| Ослабление L2 Reviewer/валидатора ради Hybrid | T-4877: fail-closed сохраняется; T-4882#18 |
| Отключение GraphRAG целиком ради логов; общий `except Exception` без batch policy | T-4878: control-plane-only breaker; unexpected остаётся со stacktrace |
| Full rewrite Summary/GraphRAG/Cover Style | Хирургические дельты в задачах зон |
| Unrelated MCA changes | Scope-check в T-4885 (вопрос «з»); commit hygiene в tasks.md |
| Полный suite «для уверенности» | Только targeted §6 + E2E §7 |

## §12 — Финальный отчёт владельцу (27131–27146)

| # | Пункт отчёта | Источник |
|---|---|---|
| 1 | Какие root causes реально найдены | evidence.md pre-fix + tasks status |
| 2 | Какие файлы изменены | git diff кандидата |
| 3 | Какие pre-fix repro были красными | evidence.md §1 |
| 4 | Какие focused tests зелёные | evidence.md §6 |
| 5 | Canary A: job id + outcome | evidence.md Canary A |
| 6 | Canary B: run id + issue number + `styled` | evidence.md Canary B |
| 7 | L2: почему раньше две failed revision и что теперь | evidence.md §4 |
| 8 | GraphRAG: quota topology + embed attempts/warnings до/после | evidence.md GraphRAG |
| 9 | Remaining risk только если реально существует | Reviewer + Orchestrator |
| 10 | Следующая MCA-задача для возврата | T-4890 |

## Противоречия / Architect

- Реального архитектурного противоречия не найдено: контракты RC-B (next_issue_number vs last_assigned), RC-C (display-only), RC-D (draft snapshot), RC-E (revision contract), §2 (single resolver), §4 (recompute findings), §5 (batch breaker) совместимы с текущими ADR и не требуют новых решений.
- Если Builder на Step 0 найдёт **генуинное** противоречие кода и §0–§12 — зафиксировать здесь как `OPEN — Architect needed` и остановиться до правок (ожидаемо: нет).
