# Quality-контракт MEMORY-07 и read-модель MEM-08 S1/S2 — привязка кандидата `e3ae13ae`

Артефакт PM: связывает требования §8 (MEMORY-07, качество/провенанс) и §9.4
(MEM-08.14…MEM-08.28, срезы S1/S2) с **проверенным кандидатом**
`e3ae13ae98d84dd8b0f3e8460043b8d54631d55c`. Продуктовый код не менялся; записаны
только плановые артефакты (этот файл, `requirements-map.json`, `plans/backlog.md`).

Обозначения источников наблюдения:

| Пометка | Значение |
|---|---|
| **[pm-code]** | PM лично прочитал код/тесты указанного коммита через `git show <sha>:<path>` в локальном репозитории |
| **[pm-run]** | PM лично запустил тесты в отдельном checkout этого кандидата (detached HEAD), команды и числа ниже |
| **[builder]** | сообщение исполнителя в handoff, первичный отчёт не приложен |
| **[reviewer]** | сообщение независимого Reviewer в handoff, первичный отчёт не приложен |
| **[pm-binding]** | решение PM по статусам/привязке требований, не продуктовое поведение |

## 1. Идентичность кандидата и отношение к проду

| Поле | Значение |
|---|---|
| Проверенный кандидат | `e3ae13ae98d84dd8b0f3e8460043b8d54631d55c` |
| Родитель | `6af6b1c8` (read-модель сообществ отдаёт только proven) |
| Родитель родителя | `c816e83c` (quality contract: provenance в источнике + PROVEN/WEAK) |
| Начало среза S1/S2 | `44a10e28` (контракт поискового ответа + read-модель сообществ) |
| Ветка | `integ/unify-release` (в `master` этих коммитов нет) |
| Прод на момент привязки | 2.58.168 @ `ea9a7141` — кандидат **является потомком** выкаченного коммита, т.е. содержит базу 2.58.168 и **не выкачен** |
| Дельта кандидата от родителя | 9 файлов, +265/−18: `bot.py`, `web/app.py`, `web/api/cognitive_map.py`, `services/memory_search.py`, 5 тестовых файлов — UI/`web/index.html` не меняется |

Проверено [pm-code]: `git merge-base --is-ancestor ea9a7141 e3ae13ae` → истина;
`git diff --stat 6af6b1c8 e3ae13ae` → только перечисленные файлы.

## 2. Изолированная проверка (что и как запускалось)

Reviewer сообщает [reviewer], что APPROVED получен после проверки в отдельном
checkout, закрывшей два прежних блокера:

1. read-модель сообществ отдавала наружу WEAK-сообщества (исправлено в
   `6af6b1c8`: наружу выходят только proven-идентификаторы активной сборки);
2. эндпоинт поиска вызывался без живого `MemoryManager`, из-за чего векторный
   канал не выполнялся и ответ выглядел как «совпадений нет» (исправлено в
   `e3ae13ae`: один инстанс менеджера из `bot.py` → `create_app(memory=…)` →
   `app.state.memory` → `search_memory`, честная деградация вместо пустоты).

PM повторил проверку независимо [pm-run] в отдельном worktree на этом кандидате
(`git worktree add --detach <WorkspaceData>/worktrees/…/memory-cognitive-02-… e3ae13ae`):

```
python -m pytest tests/test_mem08_search_read_model.py -q                     -> 42 passed
python -m pytest tests/test_evol_cog_map_api.py -q                            -> 23 passed
python -m pytest tests/test_memory_communities_retrieval.py \
                tests/test_memory_quality_contract_07.py -q                   -> 21 passed
python -m pytest tests/test_bot_main_flow.py tests/test_summary_inc01_exit.py \
                tests/test_summary_inc01_shutdown.py tests/test_webapp_avatars_ui.py -q
                                                                              -> 65 passed, 1 failed
```

Единственный провал — `tests/test_webapp_avatars_ui.py::TestAvatarFrontAudit::
test_close_and_fullscreen_buttons` (`html.count(">✕</button>") == 5`, фактически 7).
Это **предсуществующее** расхождение статической проверки админки: `web/index.html`
в кандидате побайтово равен родителю (`3c45d015…`) и в выкаченном `ea9a7141` даёт
те же 7 вхождений [pm-code]. К поиску/сообществам не относится, кандидатом не
внесено; отдельного решения по нему здесь не принимается.

## 3. Что доказано — качество и провенанс MEMORY-07

Пороги и правило (единственное место — `services/memory_communities.py:970`
`classify_community_status`) [pm-code]: `PROVEN` ⇔ `size ≥ 3` И `S ≥ 1.0` И
`S/T ≥ 0.5`, где `S = confirmed×1.0 + tentative×0.5`,
`T = S + legacy×0.25 + cooccurrence×0.1` по связям **внутри** сообщества; всё
остальное — `WEAK`. Допуск `_EPS = 1e-9` применяется только к двоичному
представлению долей (0.25+0.25), не к «почти порогу». Пороги не ослаблены под
данные.

Хранение [pm-code]: статус и метрики пишутся в **существующий**
`mca_community_builds.change_summary_json` (`proven_community_ids`,
`proven_communities`), новых таблиц/колонок и миграций нет —
`services/memory_communities.py:997 community_quality`; нет DDL, `user_version`
остаётся 44 (тест `test_build_stores_proven_ids_without_ddl`).

Провенанс в источнике (`services/summary_memory.py`, §14.1) [pm-code]:

| Изменение | Что означает |
|---|---|
| Крон-путь триплетов больше не пишет `fact_id = NULL` | факт создаётся **первым** в той же транзакции (`find_graph_fact_exact` → `insert_graph_fact` → `upsert_edge(fact_id=…)`), поэтому ребро всегда связано с фактом; повторный прогон переиспользует существующую строку (идемпотентно) |
| Субъект-атрибуция после коммита пары | `_attach_fact_provenance` вызывается после `COMMIT` (у него свои транзакции), fail-open: сбой атрибуции не отменяет уже записанные факт/ребро |
| `subject_ref_id` пишется только при `resolution == 'resolved'` | тот же `resolve_subject_ref`/`resolve_source_ref`; неизвестное имя и одноимённые остаются `unresolved` без ref — идентичность не выдумывается |
| Для `bot_self_reply` ref не пишется вовсе | собственный вывод бота не подтверждает внешний факт (C-8 §8.4/R-3) |
| `subject_ref_id` резолвится для любой факт-строки, чей субъект резолвится | включая `world_knowledge`; это и устраняет корень деградации (96 % факт-связей были legacy) |

Тесты, подтверждающие пункты (10 шт., файл `tests/test_memory_quality_contract_07.py`,
все пройдены [pm-run]): создание факта и связывание ребра в крон-пути, общий
rollback фактов и рёбер, `subject_ref` для `world_knowledge`, пустой ref при
неразрешимом имени, отсутствие ref для `bot_self_reply`, три границы порогов
(размер, `S`, `S/T`) и статус по реальным счётчикам связей, запись proven-набора
без DDL.

## 4. Что доказано — read-модель сообществ

`services/memory_search.py` [pm-code]:

| Поведение | Где | Тест |
|---|---|---|
| `proven_community_ids` читается из **активной** сборки; нормативный ключ — `proven_community_ids`, `proven_communities` добавляет метрики (берутся только строки со `status='proven'`) | `:240 _proven_community_ids` | `test_build_without_proven_ids_returns_empty_items`, `test_active_build_payload_fields` |
| Пустой proven-набор → `state='ok'`, `reason_code='no_proven_communities'`, `items=[]` **до** любой работы с подписями/метриками (не «все сообщества») | `read_active_communities` | `test_build_without_proven_ids_returns_empty_items` |
| Смешанная сборка (proven + WEAK) → в `items` только proven | `:413` | `test_mixed_build_returns_only_proven_ids` |
| WEAK никогда не показывает подпись (ни именованную, ни нейтральную как категорию) | `:413` | `test_weak_community_never_surfaces_a_label`, `test_neutral_label_never_surfaces_in_search` |
| Поисковый путь пересекает запрошенный набор с proven (слабое сообщество не подписывается и в поиске) | `:413`, `:1001` | `test_community_title_comes_from_active_build_label` |
| Битый/отсутствующий `change_summary_json` → честно пусто, «неизвестно» ≠ «всё доказано» | `:240` | `test_broken_summary_json_is_honestly_empty` |
| Payload остаётся `cog-map/1` и аддитивен (существующие поля байт-в-байт) | `web/api/cognitive_map.py` | `test_map_payload_stays_additive_with_empty_communities`, `test_existing_fields_match_golden_fixture` |

Тематический retrieval-канал фильтрует proven **самостоятельно** [pm-code]:
`services/mca_retrieval_context.py:1914 _community_candidates` читает proven-набор
активной сборки (`:1868 _active_community_quality`), `provenance_backed`
выводится из статуса (не константа `True`), нейтральная подпись не выводится,
вес ребра не подмешивается в ранжирование
(`tests/test_memory_communities_retrieval.py`: `test_weak_community_excluded_from_thematic_channel`,
`test_provenance_backed_is_derived_not_hardcoded`,
`test_build_without_proven_set_is_not_served`, `test_neutral_label_never_surfaces_in_search`).

## 5. Проверка Reviewer на трёх сообществах

[reviewer] В независимой пробе на сборке из трёх сообществ (proven + нейтральное
WEAK + именованное WEAK) в выдаче карты, в поиске и в тематическом канале
возвращён **только proven-идентификатор**; два WEAK не появились ни подписью, ни
метрикой, ни категорией. Тот же результат подтверждается независимыми тестами
PM [pm-run] (`test_mixed_build_returns_only_proven_ids`,
`test_weak_community_excluded_from_thematic_channel`).

## 6. Проверка проводки эндпоинта поиска

[pm-code] По дельте `6af6b1c8 → e3ae13ae`:

| Звено | Файл:место | Что видно |
|---|---|---|
| Создание единственного менеджера | `bot.py::on_startup` возвращает `memory`; `main()` получает его и передаёт `create_app(cache, control=control, memory=memory)` | второго инстанса нет, глобального состояния не вводится |
| Хранение | `web/app.py::create_app` → `app.state.memory` | как `cache`/`control` |
| Использование | `web/api/cognitive_map.py:952 memory_search_endpoint` берёт `request.app.state.memory` и передаёт **тот же** объект в `search_memory` | второй менеджер не создаётся |
| Наличие векторного канала | `services/memory_search.py:101 _vector_capable` → `debug.degraded`; `:827 search_memory` | без менеджера возвращается `error`/`error` с `reason_code='vector_unavailable'`, а не `empty`/`no_matches` |

Тесты [pm-run]: `test_endpoint_hands_same_manager_and_vector_channel_runs`
(перефразированный запрос даёт типизированный кандидат),
`test_context_without_manager_is_degraded_not_no_matches`,
`test_adapter_without_manager_reports_degradation`,
`test_adapter_calls_shared_retrieve_once`, `test_adapter_has_no_own_search_sql`
(второго поиска/своего SQL нет), `test_bot_passes_the_same_manager_into_create_app`,
`test_create_app_exposes_injected_manager`.

Проверенные пользовательские точки, где членство фильтруется по proven [pm-code]:
`web/api/cognitive_map.py:875` (карточка чата) и `:891` (глобальная карточка) в
`build_cognitive_map`, плюс `services/memory_search.py:1001` (подписи в ответе
поиска). Тематический канал — отдельный фильтр в
`services/mca_retrieval_context.py:1914`.

## 7. Честная граница: что этим кандидатом НЕ доказано

1. **Прод-измерение доли proven.** Комментарий самого quality-контракта
   [builder], `services/memory_communities.py` §14.2, утверждает «одно
   сообщество из 3 933 — честный размер доказанной части» (порог размера ≥ 3
   отсекает пары). Независимого замера доли proven в этом артефакте нет: в
   измерении волны 4 (`memory-07-wave34-measurement-ea9a7141.md`) proven-набор
   не считался, а сообществ там 4 158 на пяти чатах. Сколько их станет после
   исправления провенанса в источнике — не измерено: сборка на проде с новым
   кодом не запускалась.
2. **Качество подписей на проде.** На 2.58.168 все подписи были нейтральными
   («Сообщество N») из-за 86 подтверждённых/сомнительных связей из 64 432.
   Улучшение подписей после исправления провенанса не измерено.
3. **Потребление в тематическом retrieval на проде.** ON-поведение с реальной
   сборкой не наблюдалось: флаг на 2.58.168 был OFF (временный инженерный hold,
   `ED-MEMORY-07-COMMUNITIES-2026-11-09`). Кандидат переводит заводской дефолт в
   ON, но effective-state на проде ещё не проверялся.
4. **Влияние на поиск.** Вклад отфильтрованного сообщества-канала в реальную
   выдачу (состав/порядок) на проде не измерен; измерен только OFF-паритет 34/34
   предыдущей волны.
5. **S2 целиком не закрыт:** в acceptance S2 входит независимый quality/latency
   gold, которого в кандидате нет (gold-набора в репозитории не существует).
6. **S3/S4/S5 (UI-omnibox, граф, EVAL-07) не реализованы** — в кандидате нет ни
   одного клиентского/UI-файла, `web/index.html` не менялся.

Отсюда статусы: MEM-07.4/07.6 остаются `VERIFIED` (механизм), контейнер
`MEMORY-07` — `PENDING` (остались изменение-ориентированный запуск MEM-07.3 и
пользовательский показ/измерение), MEM-08-S1 закрыт, MEM-08-S2 и UI-строки
MEM-08.14…08.28 остаются `PENDING`.

## 8. Housekeeping

Отдельный checkout кандидата создан через
`workflow_housekeeping.py worktree-path` (+`git worktree add --detach`,
`register-worktree`), после прогонов оставлен без изменений (detached HEAD на
`e3ae13ae`, `git status` чист). Штатный `unit-close` (preview) **сохранил**
worktree с причиной «detached HEAD not contained in the integrated branch»:
кандидат живёт в `integ/unify-release`, а не в `master`. Поэтому checkout
намеренно оставлен до интеграции ветки — это зафиксированное решение, а не
забытая уборка; удалять его принудительно (`--force`) запрещено. Временные
файлы привязки (скрипт, вывод гейта) лежат в
`WorkspaceData/runs/…/temp-8efe062c1e/` и закрываются отдельным `run-close`;
вне `WorkspaceData/` временных файлов не создавалось.

## 9. Гейт требований (review stage, реальный кандидат)

Команды выполнялись из корня проекта; у карты нет `slice_graph.json`, поэтому
проверка идёт по слайсу:

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/memory-cognitive-02/requirements-map.json \
  --stage review --slice MEMORY-07 --candidate e3ae13ae98d84dd8b0f3e8460043b8d54631d55c
```

```
FAIL: MEMORY-07: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MEM-07.1: no evidence bound to reviewed candidate
FAIL: MEM-07.2: no evidence bound to reviewed candidate
FAIL: MEM-07.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MEM-07.5: no evidence bound to reviewed candidate
stage=review inventory=153 manual=147 scoped=7 errors=5
```

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/memory-cognitive-02/requirements-map.json \
  --stage review --slice MEM-08-SLICE --candidate e3ae13ae98d84dd8b0f3e8460043b8d54631d55c
```

```
FAIL: MEM-08-S2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MEM-08-S3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MEM-08-S4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MEM-08-S5: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=153 manual=147 scoped=5 errors=4
```

До этой привязки обе команды дополнительно падали на `FAIL: candidate mismatch;
map candidate_commit must match --candidate` (карта указывала `e4b97ce5`); после
привязки кандидата этой ошибки нет. Остальные красные строки — **реальные
открытые требования**, а не дефект карты: MEM-07.1/.2/.5 доказаны на прежних
кандидатах волн 2–4 и не переигрываются под новый срез; MEM-07.3 и контейнер
MEMORY-07 открыты; S2 не имеет независимого gold, S3/S4/S5 не реализованы.
Перекрашивать их в `VERIFIED` ради зелёного гейта запрещено.

`--stage plan` на этой карте остаётся зелёным: `stage=plan inventory=153
manual=147 scoped=0 errors=0`.
