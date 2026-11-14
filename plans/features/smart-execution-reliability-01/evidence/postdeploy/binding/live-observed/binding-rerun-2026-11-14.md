# Binding: focused live-canary rerun 2.58.200 → SMART 3 ids / FC 3 ids + честные статусы остальным

- Дата: 2026-11-14 (прогон 08:37–08:44Z). Прод: `2.58.200`,
  `0e4a144db476a1535ae3a2b79a7cce30354ad866`, ветка `release/2.58.200`, unit `admin_bot`
  active (MainPID 709883, старт 05:18:59Z без рестарта), `/healthz` 200, tracked-дерево чистое.
- Источник доказательств (read-only прогон DevOps, локальный commit `a575275d`):
  - `plans/features/smart-execution-reliability-01/evidence/postdeploy/live/canary-rerun-20261114T083723Z.md`
    (`sha256 e1450b68912dfd2345e4772ff6c4a64546fb82da03f982d6c6ee3daac717f206`);
  - `.../live/raw/smart_live_canary-20261114T083723Z.json`
    (`sha256 05d6fbb93ccc2dcb2d3a91f6750a49c45f78586b6f7ff650a2500dfad3754283`);
  - `.../live/raw/fc_live_canary-20261114T083723Z.json`
    (`sha256 05f8db0b90a1175f51dd7e33314cff2512ab2df3f16553f51d8cb50a08c9c18d`).
  Харнессы запускались с `--expect-harness-sha256` (smart `21c7ac74…`, fc `391deff8…`), sha совпали.
- Журнал unit за окна прогонов: 0 WARN / 0 ERROR / 0 CRITICAL / 0 traceback (SMART 40 строк, FC 242);
  `/healthz` 200 после каждого прогона; Telegram-отправок нет (`outbound_delivered_to_telegram=0`,
  `telegram_bot_class=StubBot`), конфигурация не сохранялась (`config_persisted=false`,
  `in_memory_overrides_restored=true`), production PG открывался только read-only SELECT'ами.
- Изменения карт (объём): **80 обязательных строк** переведены в `VERIFIED` с одной
  `production`-записью каждая (`candidate_commit` = `deployed_commit` = `0e4a144d…`,
  `artifact_path` = `canary-rerun-20261114T083723Z.md`, `artifact_sha256` = `e1450b68…`,
  в `ref` — точная строка/блок отчёта и sha256 соответствующего raw JSON),
  `verified_via: "production 2.58.200 @ 0e4a144d; focused canary re-run 2026-11-14T0837Z"`;
  строковый `postrelease_wait` снят как исполненный, историческое `approved_postrelease_wait`
  в review-записях **сохранено без изменений**.
  - SMART (40 строк): `SXR-F2-01` 18, `SXR-L5-01` 9, `SXR-L3-01` 13.
  - FC (40 строк): `SFC-12-02` 12, `SFC-7-06` 12, `SFC-13-01` 16.
- **135 строк оставлены в прежнем статусе `READY_FOR_LIVE`** с приложенной `production`-записью
  «что именно наблюдалось / чего не наблюдалось» и без каких-либо изменений `postrelease_wait`
  (его текст закреплён одобренным Reviewer `approved_postrelease_wait`; менять его вручную нельзя).

## SXR-F2-01 — BOUND (18 строк)

| Клауза приёмки | Наблюдённый факт (строка 7 `external_reads`, production, 13/13 assertions) |
|---|---|
| реальный запрос к публичному GitHub из deployed-кода | `octocat/Hello-World` README, commit `7fd1a60b…`, 12 симв., `verified=false` (честный инвариант README), `network_calls=4`, `stage=fetch` |
| вторая ветка сценария — файл исходника | `octocat/Spoon-Knife`, ref `main`, path `index.html`, commit `d0dd1f61b33d64e29d8bc1372a94ef6a2fee76a9`, 354 симв., `source_kind=file`, `verified=true` |
| прежний отказ `destination_blocked`/`stage=connect` не воспроизводится | оба реальных запроса дошли до `stage=fetch` и вернули содержимое; `destination_blocked` на разрешённом GitHub отсутствует |
| причина локализована, а не перечислена как возможная | review-уровень: расхождение pre-flight DNS (`140.82.114.5`) с фактическим peer (`140.82.112.6`) при ротации A-записей; TCP привязан к attempt-validated адресам (RED на базе `d20a7f73`: 7 failed) |
| отказ запрещённым назначениям отделён и точен | tool-path loopback/metadata → `provider_unconfigured`/`host_not_supported` (`stage=discover`, `network_calls=0`); напрямую SafeFetcher → `destination_blocked` (loopback) и `metadata_endpoint_blocked` (metadata) на `stage=resolve` |
| реальный внешний отказ | `source_missing`, `retryable=false` (без обхода прав) |

Открыто: ничего по приёмке.

## SXR-L5-01 — BOUND (9 строк)

| Клауза приёмки | Наблюдённый факт (строка 7 `external_reads`, production) |
|---|---|
| обычное разрешённое чтение публичного внешнего репозитория через Smart-модуль | production `SourceReader` прочитал `octocat/Spoon-Knife` `index.html` (`main`, commit `d0dd1f61…`), `source_kind=file`, `read_level=parsed`, 354 симв. |
| реальный сетевой запрос | `network_calls=4` на каждый публичный read |
| прохождение DNS/peer validation | соединение к разрешённому хосту установлено и завершилось успешно; для запрещённых назначений отказ возникает на `stage=resolve` (валидация адреса до connect) |
| проверенная идентичность источника | `verified=true` только для `source_kind=file`; commit+path из реального ответа, README честно `verified=false` |
| получение исходников и корректный ответ | 354 симв. реального содержимого файла (не заглушка), `error=null` |
| отказ запрещённому назначению подтверждён отдельно, SSRF сохранена | `destination_blocked` / `metadata_endpoint_blocked` (SafeFetcher) и `provider_unconfigured` с 0 сетевых вызовов (tool-path) |
| нормальное поведение при реальном внешнем отказе | `source_missing`, `retryable=false`, отчётливая причина |

Открыто: ничего по приёмке. Пользовательская доставка ответа в Telegram в этом прогоне не проверялась
(StubBot) — это транспорт, отдельная строка SFC/SXR его не требует.

## SXR-L3-01 — BOUND (13 строк)

| Клауза приёмки | Наблюдённый факт (строка 5 `capacity_scenarios`, production, 13/13, один resolver) |
|---|---|
| текущая модель GLM 5.3 Flash Uncensored | `z-ai/glm-5.3-flash-uncensored` → 1 048 576, `source=provider_catalog`, `confidence=verified`, `max_output=32 768` |
| известная модель с окном <1M | `gpt-4o-mini` → 128 000 `provider_catalog`/`verified` (16 384) |
| известная модель с большим окном | `gemini-2.5-pro` → 1 048 576 `provider_catalog`/`verified` (65 536) |
| неизвестный custom ID | `canary/custom-unknown-7f3a` → 1 000 000, `source=estimated_unknown`, `confidence=estimated`; warning не скрыт, за verified не выдан |
| смена основной модели | `gpt-4o-mini` → `effective_input_budget=100 173` |
| переход на fallback | `deepseek-flash` → 131 072 `verified_registry` |
| временная недоступность каталога | адаптеры вернули `None` (инъекция только в адаптер, resolver реальный) → 1 000 000 `estimated_unknown` |
| context length exceeded | `131 072` при `requested 140 000` разобран структурно: `proven_limit` записан, `budget_tokens=110 413`, `output_reserve=4 096` |
| единый resolver, effective значения, источник сведений | все 8 сценариев на одном resolver; `chat_model` = текущая модель чата, `resolver_enabled=true`, `live_precedence=true`; у каждого результата заполнены `source`/`confidence` |
| фактический LLM payload | связка capacity→payload в проде: `effective_input_budget=100 173` для окна 128 000; FC `evidence_budget_chars=800 000` для 1 000 000/`unknown_fallback`; реальные provider-вызовы без обрезки по ёмкости (`checkup prompt_chars=3 021`, `input_truncated=false`) |

Открыто: ничего по приёмке. Отдельного «payload на 1M-окне» прогона не делалось: связка доказана
расчётом бюджета и реальными вызовами на effective-значениях, а не расходованием максимального объёма.

## SFC-12-02 — BOUND (12 строк)

Источник: `ordinary_factcheck` (production, 17/17) + `multipart_and_short_reply` (production, 9/9),
реальный `services.factcheck_orchestrator.run_factcheck` на deployed-коде.

| Клауза приёмки | Наблюдённый факт |
|---|---|
| запрос принят | `outcome=verdict`, corr `a641ab40be384eb8ade6d7363a3ca976`, `route=envelope_temporal`, полный `stage_trace` success |
| исходная цель разрешена | `target_resolve=success`, `target_source=stored_reply`, `target_tg_present=true`, `claim_anchor_author=true` |
| предмет не исчез из-за пустого user_hint | `has_request=false`, `origin=material`, `material_chars=235`, `text_overlaps_material=1.0` — тезис остался материалом, а не пустым запросом |
| поиск относится к исходному материалу | все 3 запроса собраны из текста материала (previews совпадают с тезисом) |
| существенные утверждения не потеряны | 2 claim / 2 searched (ordinary); 4 claim / 4 searched (multipart); `claims_unchecked_due_to_budget=0`, `..._deadline=0` |
| сформирован обычный содержательный фактчек | доставлено 2 996 симв. (ordinary) / 2 424 (multipart) с разбором и источниками, `provider_failures=0` |
| многосоставное сообщение | 4 независимых утверждения, 78 кандидатов, 3 direct evidence, 1 052 симв. evidence |
| контекстно зависимая короткая реплика | short_reply: `has_request=true`, `request_chars=12`, `subject resolved_by=llm`, 1 claim, 17 кандидатов, 800 симв. evidence, verdict `supported`, доставлено 811 симв., `reply_targets=[900122]` |

Граница прогона: reply-публикация собрана production-функцией `resolve_claim_publication`
(`target_source=stored_reply`), `run_factcheck` вызван напрямую; Telegram-update и `BinaryHandler`
не исполнялись (`outbound_delivered_to_telegram=0`). Транспорт не входит в приёмку строки.

## SFC-7-06 — BOUND (12 строк)

| Клауза приёмки | Наблюдённый факт (`ordinary_factcheck`, production) |
|---|---|
| полный путь поисковик → кандидаты → EvidenceMap → claim coverage → analyst payload → validator → verbalizer → ответ | `stage_trace`: `target_resolve` → `origin_date_resolve` → `claim_decompose` → `temporal_search` → `evidence_validate` → `verdict` (corrected) → `verbalize` — все `success`; 3 запроса, 60 кандидатов, 2 claim units, `stop_reason=paths_exhausted` |
| delivered+remainder=total | `total_rows=5`, `delivered_rows=5`, `total_chars=1 797`, `delivered_chars=1 797`, `remainder=0`, `truncated=0`, `limited=false`, `budget_chars=800 000` |
| DB evidence совпадает с отправленным модели | run-row + 5 evidence rows + ledger gate, scope уникален; `DB rows == delivered` |
| старые символьные caps/скрытое сокращение на пути | `search_text_chars=20 953`, `search_text_truncated=false`, `search_text_portions=1`; `degraded_capacity=false`; `fallback_used=false` |
| успешное получение источника ≠ доступность содержимого аналитику | доставлено ровно то, что было в EvidenceMap (5 строк / 1 797 симв.); потерь между БД и payload нет |

Граница прогона: `opened=0`, `extract_successes=0` при `fetch_errors=4` — evidence собран из поисковых
выдержек; ветка «успешно открытая страница → извлечённый материал» в этом прогоне не срабатывала
(аудит восьми звеньев и мутации проверены на review-уровне, см. `review-s15-9a89e3da.md`).
Это ограничение прогона, а не расхождение delivery-инварианта.

## SFC-13-01 — BOUND (16 строк)

| Клауза приёмки | Наблюдённый факт (observability bundle всех контрольных запусков) |
|---|---|
| request/correlation ID | `a641ab40…`, `772bd391…`, `18740adb…`, `093904ae…`, `0a5a4143…` |
| фактический маршрут | `envelope_temporal` во всех запусках |
| deployed SHA | `0e4a144db476a1535ae3a2b79a7cce30354ad866`, `app_version=2.58.200` |
| effective budget state и источник | `effective_budget_state=false`, `effective_budget_source=global`, `effective_limit_sources` — 10 лимитов с источниками `default/global` |
| число запросов / кандидатов / открытых источников / claim units / объём evidence | 3/4/1/2/2 запросов; 60/78/17/34/0 кандидатов; `opened_sources=0`; 2/4/1/2/1 claim units; 1 797/1 052/800/1 200/0 симв. |
| effective model capacity | primary `1 000 000`/`unknown_fallback` → `evidence_budget_chars=800 000`, `output_reserve=100 000`; fallback `deepseek-flash 131 072 model_map` → `104 857`/`13 107` |
| причина завершения retrieval | `paths_exhausted` / `sufficient_evidence` / `providers_unavailable` |
| покрытие существенных частей и результат | `part_coverage` 2/4/1/2/1; `final_result` с verdict и `delivered_chars` 2 996/2 424/811/524/302 |

Открыто: ничего по приёмке.

## Оставлены READY_FOR_LIVE (обоснование по строке)

К каждой строке приложена `production`-запись с фактическими значениями и явным перечнем
ненаблюдённого; `postrelease_wait` не менялся, историческое `approved_postrelease_wait` сохранено.

| req_id | Строк | Почему не VERIFIED |
|---|---|---|
| `SXR-F4-01` | 11 | **Отклонение от запрошенного биндинга.** В проде подтверждены только 2 из 6 сценариев приёмки: публичный репозиторий и чтение файла по ветке/commit (+ реальный внешний отказ `source_missing`). Не наблюдались: поиск файла/символа по внешнему репозиторию, чтение по предоставленной ссылке, переход к связанным исходникам, обычный естественный запрос о коде внешнего проекта, фактический rate limit и отказ приватного репозитория. Одобренный `live-canary-plan.md` §4/волна 4 уже помечал natural-request часть как отложенную. Нужен либо расширенный harness-сценарий на эти 4 пункта, либо отдельное решение Reviewer по сужению приёмки (это изменение owner-контракта — только через нормальный intake). |
| `SXR-L1-01` | 13 | Effective-конфиг наблюдался (master OFF, `limits_enforced=false`, caps 0, fuse 0), но контрольный сценарий >4 раундов / >6 вызовов / >2 tool calls в раунде, ON-контракт и пользовательский override исполнялись только на plumbing-двойниках (`production_observed=false`). |
| `SXR-L2-01` | 5 | Только plumbing (`evidence_payload`: 13 499/13 500 симв., cap 900 с маркером) — production-путь до финального LLM payload не наблюдался. |
| `SXR-L4-01` | 9 | Локальная часть наблюдалась (89 981 симв., строки 26–1874, `verified=true`, commit = deployed, 0 сетевых вызовов), но нет использования результата в реальном ответе и сценария checkout≠deployed. Дополнительно corrective-релиз меняет `SourceReader` → требуется повторная валидация. |
| `SXR-L6-01` | 13 | Только plumbing (7 вариантов деградации, 22/22) — в проде поиск/фактчек в этих вариантах не наблюдались. |
| `SXR-L7-01` | 13 | Технические части наблюдались (журнал 1 994 симв., `verified_deployed`, отчёт 3 665 симв., latency 24 601 мс; Direct-путь с реальным продолжением `tool_router.py` 1–4000 → 4001–4041), но corrective-релиз меняет checkup/`SourceReader` → требуется повторная валидация на нём; отчёт чекапа к тому же `bundle_status=degraded`. |
| `SXR-L8-01` | 12 | Частично: I1/I2/I4 наблюдались, I3/I5/I6 — `not_run` (нет разрешённых сценариев). |
| `SFC-12-07` | 15 | Сценарии B–J — контролируемые двойники (plumbing); реальными в проде были только сценарий A и effective-значения. |
| `SFC-5-10` | 2 | Effective-конфигурация OFF наблюдалась (global + 3 чата), но проверка «при effective OFF сохранённый старый бюджет не продолжает enforcement» на production-пути не исполнялась (OFF-сценарий — двойник). |
| `SFC-13-03` | 11 | Различимость метрик — plumbing (7 stop-reason, 8/8); классификация provider failure / ON-budget / скрытого enforcement на production-метриках не наблюдалась. |
| `SFC-12-09` | 14 | **Реальное production-отклонение** (см. ниже): 3 контрактных assertion = false. |
| `SFC-14-03` | 17 | Smoke наблюдался только в деградированном состоянии провайдера (`providers_unavailable`, 0 кандидатов / 0 evidence, технический ответ 302 симв.) — содержательный сквозной результат не подтверждён. |

## Production finding SFC-12-09 (Builder investigation)

```
correlation_id           093904aea444462ebc41ae208e4ac0ee
outcome                  verdict (прогон завершился)
search_built_from_question   false
direct_answer_on_question    false
ambiguity_acknowledged       false
material_kept / user_question_identified / relevant_sources_researched /
no_old_budget_early_stop / answer_not_a_harness_echo   true
subject                  origin=mixed, 567 симв. (материал 134, запрос 127), has_request=true
queries                  2, оба построены по материалу («Африки Ближнего Востока женское обрезание…»)
retrieval                2 claim / 2 searched / 2 direct / 34 кандидата / 3 refs / 1 200 симв.
stop_reason              sufficient_evidence; verdict insufficient_evidence
reason_code              temporal_fallback_mode; fallback_used=true; verdict stage=failed; verbalize=skipped
delivered                524 симв.; мест из вопроса (Великобритания, Германия, США, Франция) нет; ambiguity note отсутствует
дополнительно            в plain_conclusion ссылки отрендерены с пустым href: `<a href=" — пересказ`
```

Класс — production (не unavailable и не сбой харнесса): вопрос отделён от материала
(`has_request=true`), но поиск собран по материалу, прямого ответа нет, неоднозначность не помечена.
Строка осталась `READY_FOR_LIVE`; разбор передан в Builder. Пустой `href` в fallback-ответе
зафиксирован как часть того же наблюдения (отдельного scope не расширяет).

## Проверка целостности правки карт

- `requirements-map.json`: сверка с `HEAD` по каждому `source_id` — изменены 116 строк
  (71 `items` + 45 `additional_requirements`); у всех изменённых строк `evidence` только
  **дополнен** одним элементом `production`, поля `source_id/source_line/source_text_sha256/
  source_excerpt/disposition/reason/req_id/slice/acceptance/live_required/live_when` не изменены;
  переход статуса только `READY_FOR_LIVE → VERIFIED` (40 строк) с удалением `postrelease_wait`
  и заполнением `verified_via`; у остальных 76 строк `postrelease_wait` побайтово прежний.
- `requirements-map-fc-amendment.json`: рабочая копия уже содержала незакоммиченные правки
  предыдущего раунда, поэтому сверка велась по фактическому результату: ровно 99 строк получили
  мою `production`-запись (40 bind: `SFC-12-02` 12, `SFC-7-06` 12, `SFC-13-01` 16; 59 note:
  `SFC-12-07` 15, `SFC-5-10` 2, `SFC-13-03` 11, `SFC-12-09` 14, `SFC-14-03` 17), статус внутри
  каждого req_id единообразен, строк без новой записи среди целевых нет, `postrelease_wait`
  сохранён у всех не-bind строк.
- Итог по картам: SMART `VERIFIED 751 / READY_FOR_LIVE 77` (было 711/117),
  FC `VERIFIED 646 / READY_FOR_LIVE 59` (было 606/99) — ровно +40 VERIFIED в каждой.

## Гейты (после привязки)

- `check --stage deploy --candidate 0e4a144d… --repo C:\Code\Python\adminbot`:
  SMART **errors=0** (`gate-deploy-smart-2026-11-14.txt`), FC **errors=0** (`gate-deploy-fc-2026-11-14.txt`).
- `check --stage release --candidate 0e4a144d… --deployed-commit 0e4a144d…`:
  SMART **exit 1, errors=77**, FC **exit 1, errors=59**; все ошибки одного класса —
  `mandatory not ['VERIFIED'] (got READY_FOR_LIVE)`
  (`gate-release-smart-2026-11-14.txt`, `gate-release-fc-2026-11-14.txt`).
- Остаются live (13 req_id, 136 строк): `SXR-A1-04`, `SXR-F4-01`, `SXR-L1-01`, `SXR-L2-01`, `SXR-L4-01`,
  `SXR-L6-01`, `SXR-L7-01`, `SXR-L8-01`; `SFC-5-10`, `SFC-12-07`, `SFC-12-09`, `SFC-13-03`, `SFC-14-03`.
  `SXR-A1-04` (1 строка) в это задание не входила: effective-значения бюджетов прогон снял, но
  перевод строки — отдельное решение Reviewer/PM.

## Чего этот прогон не доказывает

1. `SFC-12-09` — не закрыт; это открытое отклонение, а не ожидание.
2. `SFC-14-03` — чистый smoke при стабильном провайдере не получен.
3. `SXR-F4-01` — 4 production-сценария из приёмки не исполнялись.
4. `SXR-L1-01`, `SXR-L2-01`, `SXR-L6-01` — только plumbing.
5. `SFC-12-07` (B–J), `SFC-5-10`, `SFC-13-03` — только plumbing/двойники.
6. `SXR-L4-01`, `SXR-L7-01` — наблюдались на 2.58.200, но corrective-релиз меняет `SourceReader`/checkup.
7. Telegram-транспорт не исполнялся ни в одном прогоне (StubBot); доставка до Telegram не проверялась.
8. Прогон read-only: деплоя, рестарта, изменения конфигурации и отправок в чаты не было.

## Не менялись

`plans/features/smart-corrective-01/requirements-map.json`, `plans/progress_scope.json`,
`plans/workflow_state.md`, `plans/current_task.md`, `plans/owner_inputs/*`, код и тесты.

## Гигиена

Временный run `WorkspaceData/runs/…/smart-execution-reliability-01-45d7d5f19c3b/artifact-111cf1bd5c`
(`--epic smart-execution-reliability-01 --unit pm-bind-rerun --kind artifact`) содержал только
скрипты правки/сверки и копии выводов гейтов. После промоушена нужного (4 файла гейтов → эта папка,
записи в картах, binding-заметка, пункт в `plans/backlog.md`) run закрыт
`run-close --confirmed-idle --confirmed-evidence --apply`; других temporary-артефактов это задание
не создавало.
