# FC-TRUST-01 / S7 — приёмочный харнесс (12 сценариев), 28.11.2026

Роль: Builder. Слайс `FCT-S7-ACCEPT` (35 required строк).
База (продукт): `c3c0e1cb3ff88cc9f4d7c8fa2a52f1b4208dd1fc`
(ветка `feat/fct-s6-u3-aggregate-api-2026-11-28`, продукт `f6cd011e0`).
Ветка юнита: `feat/fct-s7-acceptance-harness-2026-11-28`, кандидат — tip этого
коммита (см. handoff/`git log -1`).

Изменён только новый файл `tests/test_fc_trust_acceptance.py` (+ этот evidence).
Карты, `progress_scope.json`, `workflow_state.md`, `routes.py`/`web/*`,
флаги/миграции/LLM-стадии не менялись. Продуктовые файлы не изменены
(`git diff --stat` пуст после мутационных прогонов).

## 1. Что именно проверено и чем

Харнесс — 12 детерминированных тестов (по одному на сценарий §5) + 7 явно
пропущенных live-тестов. Каждый сценарий идёт через реальные стадии:

| Стадия | Реальный вход |
|---|---|
| цель/публикация | `factcheck_service.resolve_claim_publication` (альбом, caption/OCR, forward, автор элемента) |
| допуск | `factcheck_suitability.evaluate_suitability` (`explicit_request=True`) |
| план | `factcheck_planner.build_retrieval_plan` (claim-единицы, анкоры, медиа-флаг части) |
| поиск/доказательства | `factcheck_planner.run_retrieval` (recall-гейт, якоря, открытие первоисточника, роли, независимость, даты) |
| вердикт | `factcheck_service.merge_claim_coverage` + `factcheck_orchestrator.derive_execution_state` |
| публикация | `factcheck_orchestrator.build_presentation` → `factcheck_renderer.render_factcheck` |
| безопасность | `safe_fetch.SafeFetcher.fetch_text` (реальный SSRF-guard) |

Подменяются только внешние границы: LLM-вердикт/решение предмета (готовый
JSON/`TemporalVerdict`), поисковые провайдеры (пак выдачи `PackAgg`), сеть
(`fetch_text` по карте страниц; неизвестный URL → отказ без сети), Telegram.
Тест не подменяет проверяемые решения (роли, гейт, вердикт, рендер).

Файл: `tests/test_fc_trust_acceptance.py`,
sha256 `140530ccafd79ae39a42108b130c6407c39eaf43fdaf2ae185192cb6eaebf34e`,
1360 строк, `TEST-LIFECYCLE: CONTRACT owner=FC-TRUST-01 slice=FCT-S7-ACCEPT`.

## 2. Исполнение (фактические прогоны)

Команда: `python -m pytest tests/test_fc_trust_acceptance.py -q -rs`
(Python 3.12.0, `.venv` репозитория, worktree S7).

| Прогон | Результат | Raw |
|---|---|---|
| 19 collected (12 det + 7 live) | **12 passed, 7 skipped** (3.96 s), повторы GREEN | `raw/green-acceptance.txt` |
| Семейство fc_trust — **9 файлов** (acceptance + target + verdict + s4_evidence + render + s5_writer + s6_aggregates + s6_aggregate_api + s6_run_link; БЕЗ retrieval и s1_contract) | **165 passed, 7 skipped** (12.97 s) | `raw/green-family.txt` |
| Соседи: retrieval + admission + s1-contract | **118 passed, 1 failed** — падение в `test_evol_fc_admission.py` **предсуществующее на базе** (см. §5) | `raw/green-neighbors.txt` |
| Предсуществующее падение отдельно на базе `c3c0e1cb3` | **1 failed** (тот же тест, без файла S7) | `raw/preexisting-admission-failure-at-base.txt` |

Список skip-ов (7, полные причины — `raw/green-acceptance.txt`):

1. `test_live_s7_01_real_telegram_targets_replay` — реальные Telegram-входы
   (Reply/forward/caption/альбом/UID) + capture-bot (FCT-022/101-106/701).
2. `test_live_s7_03_real_provider_fresh_claim` — действующий SearchAggregator
   и реальные ключи на свежем утверждении (FCT-153/155/156/158/175/223).
3. `test_live_s7_08_verdict_parity_and_mironov` — прод-конфигурация вердикта:
   паритет дата/без-даты, истинная новость, два чата, Миронов 10.11.2026
   (FCT-503/504/604/1002/021/162-164/150).
4. `test_live_s7_11_writer_prose` — живой Writer (проза/даты/стиль;
   FCT-174/802/803/805).
5. `test_live_s7_11_sent_text_after_deploy` — фактически отправленный текст по
   `correlation_id` (FCT-176), только после деплоя.
6. `test_live_s7_12_reviewer_mutation_and_regression` — мутационный прогон
   Reviewer'а + регресс direct/vision/summary/search (FCT-179/180).
7. `test_live_s7_12_effective_state_after_deploy` — effective-state прода и
   фактические агрегаты (FCT-316/194/225/227/195).

Skip-тесты намеренно падают `AssertionError`, если их запустить без снятия
skip: структурная проверка не выдаётся за живой прогон.

## 3. Матрица «сценарий → req_id → статус»

| № | Сценарий §5 | req_id | Детерминированный тест | Live / остаток |
|---|---|---|---|---|
| 1 | 5.1/5.2/5.24 forward+календарь, альбом, анкоры | FCT-150, FCT-151, FCT-173, FCT-022, FCT-101 | `test_s7_01_forwarded_album_keeps_per_author_anchors` | FCT-022/101 — только live (s7_01) |
| 2 | 5.3 сбой OCR только у медиа-части | FCT-152 | `test_s7_02_broken_ocr_flags_only_the_media_part` | — |
| 3 | 5.4/5.9 смысл без лексического совпадения | FCT-153, FCT-158, FCT-001 | `test_s7_03_anchor_bridges_language_and_pack_alone_is_not_evidence` | реальная семантика провайдера — live (s7_03); FCT-001 — det + live (s7_08) |
| 4 | 5.5 ник участника ≠ публичная персона | FCT-154, FCT-106 | `test_s7_04_chat_participant_nickname_is_not_public_person` | FCT-106 (RFL) — live (s7_01) |
| 5 | 5.6/5.7 один первоисточник; перепечатки | FCT-155, FCT-156 | `test_s7_05_single_quality_source_suffices_and_copies_are_one_group` | свежая новость на реальном провайдере — live (s7_03) |
| 6 | 5.8/5.10 off-topic вне evidence и ссылок | FCT-157, FCT-159, FCT-020 | `test_s7_06_off_topic_source_never_reaches_evidence_or_links` | — |
| 7 | 5.11/5.12 единицы/масштаб и причинность | FCT-160, FCT-161 | `test_s7_07_number_mismatch_and_correlation_do_not_confirm` | — |
| 8 | 5.13–5.15 per-claim coverage, mixed | FCT-162, FCT-163, FCT-164, FCT-021, FCT-503 | `test_s7_08_per_claim_coverage_is_honest_and_mixed_is_real` | FCT-503, 504/604/1002 — live (s7_08) |
| 9 | 5.16–5.21 уточнение, техстатус, даты, логика | FCT-165, FCT-166, FCT-167, FCT-168, FCT-169, FCT-170 | `test_s7_09_refinement_technical_dates_and_logic` | FCT-169 — только структурная часть; проза — live Writer |
| 10 | 5.22/5.23 мем и Reply-контекст | FCT-171, FCT-172 | `test_s7_10_meme_and_reply_context_resolution` | — |
| 11 | 5.25–5.27 Writer, провайдер, отправленный текст | FCT-174, FCT-175, FCT-176, FCT-802, FCT-803, FCT-805 | `test_s7_11_public_boundary_and_prompt_canon` (det-часть) | FCT-175 — live; FCT-176 — det только граница ссылок, отправка live; проза — live |
| 12 | 5.28–5.30 конкуренция, инъекция/SSRF, мутация | FCT-177, FCT-178, FCT-179, FCT-180 | `test_s7_12_concurrency_injection_and_mutation` | FCT-179 мутация Reviewer'а и FCT-180 полный регресс/качество — live (s7_12) |

Процессные строки: **FCT-140** (Reviewer сам подбирает не использованные при
разработке формулировки) и **FCT-180** (оценка качества доказательств
Reviewer'ом) — обязательства Reviewer'а, не кодируются как тест; в харнессе
есть только их техническая часть (свежий кандидат, trace, мутационная
чувствительность).

## 4. Дискриминация (RED на мутациях продукта, файл восстановлен)

Обе мутации — временные правки продукта, затем `git checkout`/обратный патч;
после восстановления `git diff --stat` пуст, полный прогон снова GREEN
(`raw/green-after-mutations.txt`).

1. **S7-M1** — `services/search_aggregator.py`, `claim_relevance`:
   `causal_missing = False` (причинная связка считается доказанной).
   RED: `test_s7_07_number_mismatch_and_correlation_do_not_confirm` —
   причинный тезис становится `confirmed` (`raw/red-mutation-m1-causal.txt`).
2. **S7-M2** — `services/factcheck_planner.py`, `_independence_group`:
   `return ""` (перепечатки не группируются).
   RED: `test_s7_05_single_quality_source_suffices_and_copies_are_one_group` —
   группа независимости пустая (`raw/red-mutation-m2-copies.txt`).

## 5. Найденное, но НЕ относящееся к S7

`tests/test_evol_fc_admission.py::TestScenario7InsufficientEvidence::test_insufficient_evidence_is_not_no_claim`
падает **на базовом коммите без файла S7** (`raw/preexisting-admission-failure-at-base.txt`):
при вердикте `insufficient_evidence` без retrieval рендерер отдаёт технический
заголовок «поиск недоступен» (S4-U2 `execution_status`), а тест ждёт
«недостаточно данных». Это предсуществующее расхождение кандидата, не
регрессия harness'а; требует решения в S8/бэклоге (ослабить нельзя без
разбора, чинить продуктовое поведение или ожидание теста — решение не S7).

## 6. Честный остаток по строкам (не выдано за VERIFIED)

Не покрыто/покрыто частично этим юнитом:

| Строка | Остаток |
|---|---|
| FCT-140 | не кодируется: подбор новых формулировок — процесс Reviewer'а |
| FCT-175 | только live: настоящий провайдер и ключи |
| FCT-176 | детерминирована только граница «ссылки ⊆ EvidenceMap»; фактически отправленный текст — после деплоя |
| FCT-150 | анкоры/forward/альбом — детерминированно; «принятие ≠ предложение» зависит от открытого FCT-113 (нет смыслового производителя `decision_status`), живой кейс — s7_08 |
| FCT-169 | структурная часть (`valid_from` будущего правила) — детерминированно; проза «не выдано за состоявшееся» — живой Writer |
| FCT-022, FCT-101–106, FCT-701 | RFL: только живой replay реальных Telegram-входов |
| FCT-503, FCT-504, FCT-604, FCT-1002 | только live (прод-конфигурация/паритет) |
| FCT-179, FCT-180 | техническая часть — детерминированно; мутационный прогон и оценка качества — Reviewer/live |

Ни одна строка не переведена в VERIFIED этим артефактом.

## 7. Конфигурация и ограничения

- Effective-конфигурация базы: `FACTCHECK_PIPELINE_V2_ENABLED=True`
  (`config/settings.py`), планировщик активен; гейт вызывается напрямую,
  поэтому его env-флаг не переключался. Флаги/hot-config в тестах не меняются.
- Бюджеты OFF (`FactcheckLimits(budgets_enabled=False)`) — как в S3-тестах:
  ограничение прогона только содержанием, не временем.
- Сеть запрещена: любой `fetch_text` инжектируется; неизвестный URL —
  исключение; провайдеры подменены паком. Telegram-бот не вызывается.
- Ограничение: envelope-ветка `run_factcheck` целиком требует LLM-сервис,
  поэтому вердикт/рендер проверяются теми же функциями, что использует
  `_run_inner`/`_run_envelope_branch` (шаг пер-частной медиа-оговорки
  воспроизведён явно и помечен). Это stage-level приёмка, не «полный
  `run_factcheck` с мок-LLM».
- `owner_live_checks`, device-чек-листы, ожидание владельца не создавались.

## 8. Гигиена

- Временные probe/мутационные скрипты — в
  `C:\Users\main\AppData\Local\Temp\opencode\fct_s7_*`, удалены после работы.
- Продуктовые файлы не изменены; `git status` содержит только новый тест и
  этот evidence-каталог. Рабочее дерево S7 зарегистрировано
  `workflow_housekeeping.py` (`worktree-path` + `register-worktree`).

---

# RV-S7-01..08 — исправления по ревью r1 (раунд 2), 28.11.2026

Этот раздел **заменяет числа и перечень покрытия** из §1–§8 выше: §1–§8
описывают раунд 1 и оставлены как история. Новые прогоны — `raw/rv2-*`;
прошлые raw-файлы не переписаны.

Кандидат раунда 2: ветка `feat/fct-s7-acceptance-harness-2026-11-28`,
tip — коммит этого исправления (см. handoff/`git log -1`), база
`c3c0e1cb3`. Продуктовые файлы не менялись (все мутации откачены).

## RV-S7-01 (High) — настоящий `run_factcheck`

Исправлено: вход приёмки переведён на
`factcheck_orchestrator.run_factcheck(req, service=…, db=…, bot=capture)` для
оркестраторных сценариев:

- **сц.2 (FCT-152)** — envelope-ветка: двойник `check_claim_envelope` получает
  реальный `retrieval` и вызывает продуктовый `merge_claim_coverage`;
  пер-частная медиа-оговорка исполняется шагом `_run_inner` (1936–1953), а не
  тестом. Дублирующий шаг удалён из тестовых хелперов.
- **сц.6 (FCT-157/159/020)** — доставка через `run_factcheck` (legacy-ветка),
  проверяется фактически отправленный текст.
- **сц.8 (FCT-162/163/164/021)** — `run_factcheck` envelope: реальный merge
  внутри двойника LLM-границы, реальные заголовки/доставка.
- **сц.9 (FCT-167)** — `run_factcheck` legacy: технический заголовок и
  `rate_limit` различаются в фактически доставленном тексте.
- **сц.12 (FCT-177)** — два `run_factcheck` одновременно (см. RV-S7-03).

Тавтологичный ассерт `presentation.notice == ""` удалён. Остальные сценарии
(target-анкоры, роли/покрытие одной стадии, канон промптов) по-прежнему
вызывают продуктовые стадии напрямую — это явно указано в docstring каждого
теста.

Проверка: **мутация A** `services/factcheck_orchestrator.py` `if _media_parts:`
→ `if False and _media_parts:` даёт **RED** на сц.2
(`assert '<i>' not in text`), файл откачен — `raw/rv2-red-mutation-a-media-step.txt`.

## RV-S7-02 (High) — FCT-160 дискриминирован

Исправлено: в сц.7 добавлен кейс **одного и того же числа `658` с разной
единицей** (`658 млрд` против `658 миллионов`) и положительный контроль
(`658 млрд` против `658 млрд`). Ответ обязан различаться: несовместимая
единица → `conflicting_evidence`/не `supports`, совпадающая → `confirmed`.

Проверка: **мутация B** `search_aggregator._unit_classes` → `return set()`
даёт **RED** на сц.7, файл откачен — `raw/rv2-red-mutation-b-units.txt`.
Контроль C (`causal_missing=False`) остаётся **RED** на сц.7 —
`raw/rv2-red-control-c-causal.txt`.

## RV-S7-03 (Medium) — FCT-177 на реальном общем состоянии

Исправлено: вместо двух независимых агрегаторов/подставленного `chat_id` —
два одновременных `run_factcheck` в разных чатах на **общем** реальном
`ChatConcurrencyPool`, общем `FakeCache` и общей durable-БД. Проверяется:
раздельные сообщения в каждом capture-bot (нет чужих ссылок), два слота пула
по чатам, две run-строки с разными `chat_id/claim_text/correlation_id`.

## RV-S7-04 (Medium) — FCT-165/FCT-166

Исправлено:

- **FCT-165**: первая базовая выдача — *неподходящий* сниппет (не
  доказательство), уточняющий запрос (purpose=`refine`) находит
  первоисточник; в трассе части видны `base` и `refine` попытки.
- **FCT-166**: каскад проверяется **реальным `SearchAggregator`**: уровень
  Tavily отвечает пусто, уровень Exa находит материал; в трассе части
  `provider=exa`, `outcome=ok`.

## RV-S7-05 (Medium) — именованные кейсы

Исправлено:

- **FCT-020/159/001** — кейс «изображение о тестостероне + Reddit о датировке
  фотографии» воспроизведён: статья не `supports/qualifies`, не в ссылках.
- **FCT-150** — «Миронов, 10.11.2026»: forward-канал, дата публикации
  `2026-11-10` (provider) отделена от периода тезиса 2027; `USD/RUB` из OCR и
  ник участника не попадают в запросы/evidence.
- **FCT-151** — тот же пост **без изображения**: текст/план/поиск не
  ухудшаются.

## RV-S7-06 (Low-Medium) — live-тесты исполняемы

Заглушки `raise AssertionError` удалены. Тела live-тестов выполняют реальные
вызовы: `SearchAggregator` + `SafeFetcher` на свежем утверждении, реальный
`FactCheckService` + `run_factcheck`, чтение развёрнутой БД
(`mca_bot_outputs`), read-only `/healthz` прода. При снятии skip они падают
или проходят по фактической причине (нет ключей/сети/БД), а не по
`raise NotImplementedError`. Процессный мутационный прогон Reviewer'а
(`test_live_s7_12_reviewer_mutation_process`) — честный `pytest.skip` с
причиной «process: выполняется Reviewer'ом».

## RV-S7-07 (Low) — состав семейства

Исправлено: семейство — **9 файлов** (acceptance + target + verdict +
s4_evidence + render + s5_writer + s6_aggregates + s6_aggregate_api +
s6_run_link; БЕЗ `test_fc_trust_retrieval.py` и `test_fc_trust_s1_contract.py`).
Точная команда и результат: `raw/rv2-green-family-9files.txt` — **165 passed,
7 skipped**.

## RV-S7-08 (Low) — `acceptance.md` в ветке

Исправлено: в ветку добавлены `acceptance.md`
(sha256 `208dc68a35d189ab73544eec20476fd23d44b7672e414769615c642d603c2e3e`)
и `acceptance.md.sha256`; ссылка теста/документа разрешается внутри кандидата.

## Фактические прогоны раунда 2

| Прогон | Результат | Raw |
|---|---|---|
| Харнесс, 19 collected | **12 passed, 7 skipped** (3.98 s) | `raw/rv2-green-acceptance.txt` |
| Семейство 9 файлов | **165 passed, 7 skipped** (14.53 s) | `raw/rv2-green-family-9files.txt` |
| Соседи (retrieval + admission + s1_contract) | **118 passed, 1 failed** (предсуществующее, см. §5) | `raw/rv2-green-neighbors.txt` |
| Мутация A (медиа-шаг выключен) | **1 failed** на сц.2 | `raw/rv2-red-mutation-a-media-step.txt` |
| Мутация B (единицы игнорируются) | **1 failed** на сц.7 | `raw/rv2-red-mutation-b-units.txt` |
| Контроль C (причинность) | **1 failed** на сц.7 | `raw/rv2-red-control-c-causal.txt` |
| После откатов | **12 passed, 7 skipped**; `git diff` — только тест | `raw/rv2-green-after-mutations.txt` |

## Что осталось непокрытым после правок (честно)

| Строка | Остаток |
|---|---|
| FCT-140 | процесс Reviewer'а (подбор новых формулировок) — не кодируется |
| FCT-174 | канон/граница — детерминированно; живая проза/стиль — только live |
| FCT-175 | только live (реальный SearchAggregator и ключи) |
| FCT-176 | READY_FOR_LIVE: граница ссылок детерминирована; факт отправки — после деплоя |
| FCT-169 | структурная часть (будущий `valid_from`); проза «не выдано за состоявшееся» — live Writer |
| FCT-150 (часть) | «принятие ≠ предложение» зависит от FCT-113 (нет смыслового производителя `decision_status`); анкоры/дата/ник/USD — покрыты |
| FCT-022, FCT-101–106, FCT-701 | RFL: только live replay реальных Telegram-входов |
| FCT-503, FCT-504, FCT-604, FCT-1002 | только live (прод-конфигурация/паритет) |
| FCT-179 | техническая часть — детерминированно; мутация Reviewer'а — процесс |
| FCT-180 | техническая часть (мутационная чувствительность) — есть; полный регресс direct/vision/summary/search и оценка качества — Reviewer/релиз |

Ни одна строка не переведена в VERIFIED этим юнитом.
