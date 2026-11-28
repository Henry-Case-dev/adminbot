# FC-TRUST-01 — приёмочная матрица S7 и фактический остаток до DONE (PM, 28.11.2026)

Роль: PM, read-only. База: выложенный **`3a78484b92a6f3ba1273360e4a34de396dcf52f1`** (2.58.271,
ветка `release/2.58.271`). Источник истины — `plans/features/fc-trust-01/requirements-map.json`
(208 строк: 161 `items` + 47 `additional_requirements`; из них **141 required**).

Карты, `progress_scope.json`, `workflow_state.md`, продуктовый код и тесты **не редактировались**.
Изменён только этот каталог evidence. Ни одна строка карты не переведена в другой статус:
ниже — предложения дельты (§9), а не применённые изменения.

## 0. Метод и границы

- Полный перебор обсех списков карты скриптом (без ручного выборочного чтения): группировка
  `(slice, disposition, status)`, перечисление `req_id`, наличие `evidence`.
- Проверка фактического кода — по блобу выложенного SHA (`git show 3a78484b9:...`), а не по рабочему
  каталогу: **master (`d1b4334`) не содержит продуктового кода эпика** (см. §8, п.2). Все прогоны
  выполнены в отдельном detached-worktree на `3a78484b9` (см. §7).
- Два целевых прогона исполнены в этом проходе (сырые выводы — `raw/`), остальные проверки
  перечислены как точные команды, но в этом проходе не исполнялись; это указано в колонке
  «текущий статус доказательства» честно, без выдачи плана за результат.
- Никаких сценариев «на качество» не выдумано: только наблюдаемые контракты из acceptance-полей
  карты (source `plans/owner_inputs/2026-11-11-fc-trust-01-current-task-excerpt.md`).

## 1. Фактическое состояние строк (required)

| Слайс | required | VERIFIED | REVIEW | READY_FOR_LIVE | PENDING | Открытые `req_id` |
|---|---|---|---|---|---|---|
| `FCT-S0-CAUSE` | 22 | 0 | 0 | 0 | 22 | FCT-209×2, FCT-211×2, FCT-011×5, FCT-131, FCT-132, FCT-133, FCT-134, FCT-135, FCT-136, FCT-214, FCT-212, FCT-010, FCT-012, FCT-130, FCT-137, FCT-190 |
| `FCT-S1-CONTRACT` | 14 | 10 | 4 | 0 | 0 | FCT-113×4 |
| `FCT-S2-TARGET` | 10 | 2 | 0 | 8 | 0 | FCT-022, FCT-101…106, FCT-701 |
| `FCT-S3-RETRIEVAL` | 17 | 16 | 1 | 0 | 0 | FCT-192 |
| `FCT-S4-EVIDENCE-VERDICT` | 15 | 9 | 3 | 0 | 3 | FCT-503, FCT-1001, FCT-114 (P); FCT-504, FCT-604, FCT-1002 (R) |
| `FCT-S5-RENDER` | 6 | 3 | 3 | 0 | 0 | FCT-802, FCT-803, FCT-805 |
| `FCT-S6-OBSERVABILITY` | 9 | 0 | 4 | 0 | 5 | FCT-901…904 (R); FCT-905, FCT-906, FCT-316, FCT-317, FCT-194 (P) |
| `FCT-S7-ACCEPT` | 35 | 0 | 0 | 0 | 35 | FCT-020, FCT-021, FCT-150…179, FCT-001, FCT-140, FCT-180 |
| `FCT-S8-RELEASE` | 13 | 0 | 0 | 0 | 13 | FCT-220…227, FCT-195, FCT-196, FCT-197, FCT-198, FCT-208 |
| **Всего** | **141** | **40** | **15** | **8** | **78** | **101 открытая строка, 92 различных `req_id`** |

Сверка с `workflow_state.md`: «40 verified / 15 review / 8 ready-for-live / 78 pending of 141»
совпадает. Дополнительно в карте 25 duplicate-строк (PENDING) и 42 context-строки — они не входят
в required и не являются работой; in-scope остаток считается только по required.

## 2. Что закрывается существующими артефактами (без нового кода)

| Группа | `req_id` | Готовое доказательство | Что осталось сделать (не код) |
|---|---|---|---|
| Сверка/порядок эпика | FCT-209×2, FCT-211×2, FCT-212, FCT-214, FCT-130, FCT-137 | `evidence/readiness-2026-11-27.md` (очередь, HEAD, деревья, deployed SHA, переиспользование), `s4-design §0`, `release-2.58.271` на ветке релиза | один analysis-артефакт S0 (`plans/features/fc-trust-01/analysis/**`) со таблицей «строка → артефакт → SHA»; продукт не меняется |
| Адресная сверка прода | FCT-190 | `release-2.58.271/deploy-2.58.271.md` (head, 3 источника версии, схема v50, routes/appjs/prompts sha), `raw/deploy-identity.txt` | добавить один read-only trace инцидента либо явно записать его утрату и воспроизведение на обезличенном оригинале (частично даёт §5.1 в S7) |
| Контрольная база 4 ссылок | FCT-011×5, FCT-010, FCT-012 | acceptance-поля + существующий retrieval без whitelist | доказать отсутствие whitelist в коде (grep по 4 URL в `services/`) + прогон того же тезиса без этих ссылок через S7-харнесс |
| Сверка старых карт | FCT-131…136 | карты PVR-FC/FCP/ASAP-FC/EVOL существуют | таблица «старая строка → статус/evidence/deployed SHA → reused/нужен фикс» (D-S8-1, работа PM/Orchestrator, не Builder) |
| Регистрация параметров и effective | FCT-906, FCT-317 | `services/param_catalog.py:2983` — `limits.factcheck_max_queries_total` **уже зарегистрирован** с описанием влияния (прежний gap `verification_findings.unregistered_admin_param` устарел); тесты `test_fc_trust_retrieval.py::test_factcheck_owner_params_are_registered_for_admin`, `…test_admin_config_shows_factcheck_defaults_before_first_save`, `…test_owner_value_reaches_effective_limits_with_provenance` — **7 passed на 3a78484b9** (`raw/green-fct906-param-coverage.txt`) | связать эти прогоны как row-bound evidence (REVIEW), затем живой снимок effective на проде → VERIFIED |
| Отказы/лимиты не списываются зря | FCT-1001 | `tests/test_evol_fc_admission.py` (refund, single-flight/antispam, `test_retry_after_early_refusal_not_blocked`), плюс `test_fc_trust_retrieval.py` (cancelled/rate_limit/global_deadline) — **57 passed** вместе с render-набором (`raw/green-fct1001-904-adjacent.txt`) | связать прогон как evidence → REVIEW; «live-наблюдение» из S4-U2 §7 для этой строки не обязательно (контракт детерминирован) |
| Публичный текст без внутренних токенов | FCT-904 (часть) | `tests/test_fc_trust_render.py::TestNoInternalTokens` (в тех же 57 passed) | добавить проверку остальных публичных путей (ambiguous-реплика, fallback-текст) — это новый тест, см. §3 |
| Семантика claim↔passage | FCT-192 | S3-ревью + детерминированные relation-тесты (`test_displayable_relation_always_has_basis`, `test_assertion_type_from_passage_in_pipeline`) | требуется решение, чем доказывается «по существу» (см. §10, п.2) |
| Ложный mixed / execution_status | FCT-504, FCT-604, FCT-1002 | `fct-s4-u2` implementation+review (24 теста, negative control) + `test_fc_trust_verdict.py` | живой прогон в прод-конфигурации (паритет дата/без даты, истинная новость, два чата) — §5 |

Вывод: **без нового кода** разблокируются S0 (22 строки, артефакт-работа), FCT-906/FCT-317/FCT-1001
(по 1 строке, связать уже зелёные прогоны), FCT-904/905 — частично (нужен тест на прочие публичные
пути). Остальные REVIEW/PENDING требуют конкретного шага из §3–§5.

## 3. Что требует нового кода/теста (детерминированно, без деплоя)

| `req_id` | Установленный разрыв | Где | Наблюдаемая проверка |
|---|---|---|---|
| **FCT-113 ×4** | ось `assertion_kind` есть, но два из четырёх типов **не производятся**: `git grep` по `3a78484b9` показывает единственного писателя `factcheck_planner._assertion_kind_for(... hint=...)`, и ни один вызывающий не передаёт `decision_status` / `normative_state_on_date` (`_ATTRIBUTION_SENSITIVE_SOURCES`, `_IMAGE_CLAIM_SOURCE_TYPES` дают только attribution/image). Значит «четыре типа различаются» наблюдаемо лишь для двух | `services/factcheck_planner.py:370-400,966,1390`, `services/factcheck_service.py:2756` | тест: тезис «предложение перенести каникулы» → `decision_status`; «закон действует с 01.01.2027» → `normative_state_on_date`; `unknown` не подменяется. Источник типа — смысловой (LLM/Analyst), не лексикон |
| **FCT-901, FCT-903, FCT-194** | S6-U2 даёт только вычисление (`aggregate_factcheck_snapshots`, `summarize_factcheck_aggregates`), **API/UI нет**: в `web/api/routes.py` есть только `/factcheck/temporal/runs[/{id}]`, `web/app.js` агрегатов не запрашивает | `web/api/routes.py`, `web/app.js` (существующая вкладка «Проверки во времени») | `GET /api/factcheck/temporal/aggregate` (global-admin, 401 без сессии) + блок сводки в существующей вкладке; счётчики без durable-сигнала (`entity_collision`, `media_partial`) остаются `None` и в UI подписаны «не измеряется» (D-S6-2) |
| **FCT-904, FCT-905** | нет теста «ключи/сырой текст чата не попадают в run/evidence/события» и нет полного перечня запрещённого во **всех** публичных путях (вердикт, ambiguous-реплика, fallback) | `tests/test_fc_trust_observability.py` (новый), `services/factcheck_service.py` только если тест вскроет протечку | тест-инвентарь публичных путей + assertion «нет trace id / CoT / промптов / конфигов / API-ключей / сырого текста чата»; мутация «источник = сохранённое поле вместо effective» → RED |
| **FCT-316** | заводское значение `FACTCHECK_PIPELINE_V2_ENABLED` = `False` (`config/settings.py`), при этом effective на проде `true` (`release-2.58.264/raw/effective-flags.txt`) — нарушает правило проекта 09.11.2026 (готовое — по умолчанию ON при первом выкладе) | `config/settings.py` (только дефолт; PG/hot/per-chat overrides не трогать) | тест дефолта + снимок effective **в обоих состояниях** (D6 из `s4-design`) |
| **FCT-803/802/805** | детерминированная часть закрыта (payload-даты, unknown, канон промптов), «проза» — живой Writer-прогон | без кода: `-m live_provider` в S7-харнессе | текст ответа содержит даты один раз, unknown честно, `factcheck_prompts.py` sha256 = `4cd1e893…` (пин выложенного 3a78484b9) |
| **FCT-192** | «оценка связки по существу» паркована из S3 в S4 (P-S3-1), но S4 явно исключил `relation_evidence.py` (D4) — **обязательство без владельца** | решение PM/Architect (§10, п.2) | либо доказать, что семантическую оценку даёт существующий Analyst-выход (тогда — evidence с S7-прогона), либо назначить отдельный шаг |
| **FCT-114** | по S4-U2 §7 предлагалась RFL «без изменений» (S3/attribution-тесты), в карте осталась PENDING — дельта не применена | без кода | связать `test_fc_trust_retrieval.py` (attribution/no-name-strip) прогоном на 3a78484b9 |

## 4. Что закрывается только живым прогоном / деплоем

### 4.1 Живой прогон без деплоя (реальные ключи, локально/на выложенном дереве)

| `req_id` | Что именно проверяется живьём | Команда |
|---|---|---|
| FCT-022, 101–106, 701 (8 строк RFL) | реальные Telegram-входы: Reply/forward/caption/альбом/UID | реплей сохранённых реальных сообщений через `run_factcheck` + capture-bot (без отправки): `python -m pytest tests/test_fc_trust_acceptance.py -q -k "target_live"` |
| FCT-504, 604, 1002 | паритет дата/без-даты в прод-конфигурации, истинная новость → не «недостаточно», два чата одновременно | `-m live_provider` + `-k "verdict_live or concurrent"` |
| FCT-503 | Миронов: дата публикации ≠ период календаря ≠ текущий правовой статус | `-m live_provider -k scenario_mironov` |
| FCT-802, 803, 805 | живой Writer: даты один раз, unknown честно, стиль/канон | `-m live_provider -k writer_live` |
| FCT-175, 223 | настоящий SearchAggregator на действующих ключах, свежее (не использованное при разработке) утверждение | `-m live_provider -k "real_provider fresh_claim"` |

Ключи есть в локальном `.env` (`TAVILY_API_KEY`, `EXA_API_KEY`, `OPENROUTER_API_KEY`), доступ
владельца не требуется; сообщения в рабочие чаты не отправляются (D-S7 `decisions.md`).

### 4.2 Только после деплоя следующего релиза

| `req_id` | Что проверяется |
|---|---|
| FCT-316, 194 | effective-значения на проде после смены дефолта + фактические прогоны/агрегаты в панели |
| FCT-223 (финальная часть), FCT-225, FCT-227, FCT-195 | release SHA/версия/DDL/health, сверка старых карт, отчёт, отсутствие диагностического спама |
| **FCT-176** | фактически отправленный текст: `mca_bot_outputs` по `correlation_id` = `pipeline_run_id` |

Про FCT-176 отдельно: реальная отправка в рабочий чат запрещена (FCT-195), отдельного тестового чата
в конфигурации нет (`TEST_CHAT_ID` отсутствует, один `API_TOKEN`). Значит закрытие возможно только
(a) изолированным тестовым чатом, который может дать лишь владелец, либо (b) пассивным наблюдением
первого естественного фактчека. Оба варианта — не блокер эпика: строка паркуется как
`delivered_awaiting_evidence` после деплоя, а не превращается в задание владельцу.

## 5. Приёмочная матрица S7 (12 сценариев, покрывают 35 строк слайса)

Способ проверки — один харнесс `tests/test_fc_trust_acceptance.py` (write-scope S7), вызывающий
**настоящий вход** `services.factcheck_orchestrator.run_factcheck(req, service=…, db=…, bot=capture)`
и складывающий trace стадий, текст ответа, список ссылок и класс вердикта. Сейчас файла **нет**
(`git ls-tree 3a78484b9 -- tests` содержит 11 `test_fc_trust_*`, но не acceptance-харнесс).
Существующие наборы покрывают детерминированные под-части и указаны в колонке статуса.

| № | §5 | `req_id` | Проверка агентом (точная команда) | Ожидаемый наблюдаемый результат | Текущий статус доказательства |
|---|---|---|---|---|---|
| 1 | 5.1, 5.2, 5.24 | FCT-150, 151, 173; FCT-022/101 RFL | `pytest tests/test_fc_trust_acceptance.py -q -k "target_and_album"`; `-m live_provider` для 5.1 | для пересланного поста с календарём `target_resolve=success` с реальными якорями (chat/message_id/forward origin), album даёт отдельные claim-якоря и не сливает авторов; «предложение ≠ принято» | харнесса нет; детерминированно частично — `test_fc_trust_target.py::TestSevenInputShapes/TestAlbumCarrier` (зелёные в S2-ревью) |
| 2 | 5.3 | FCT-152 | `-k media_partial` | сбой OCR помечает только медиа-часть (`unverified_media`/`media_partial`), текстовая атрибуция проверяется | харнесса нет; `test_fc_trust_s4_evidence.py::TestUnverifiedMediaPerPart`, `test_fc_trust_render.py::TestUnverifiedMediaPerPart` |
| 3 | 5.4, 5.9 | FCT-153, 158 | `-k semantic_retrieval` | тезис другими словами/на другом языке находит первоисточник; низкий лексический overlap не отказ | `test_fc_trust_retrieval.py::test_low_overlap_pack_returns_instead_of_hard_failure`, `…pack_is_not_evidence_end_to_end` |
| 4 | 5.5 | FCT-154; FCT-106 RFL | `-k entity_separation` | участник с ником «Миронов» не сливается с публичной персоной; ник не подтверждение | `test_fc_trust_target.py::TestIdentity` |
| 5 | 5.6, 5.7 | FCT-155, 156 | `-k positive_and_copies` | один качественный первоисточник → `supported`; перепечатки — одна группа независимости, не «несколько источников» | `test_fc_trust_retrieval.py::test_one_quality_primary_suffices_and_copies_are_not_independent`, `test_copies_share_independence_group` |
| 6 | 5.8, 5.10 | FCT-157, 159; FCT-020 | `-k off_topic` | off-topic/unrelated не попадает ни в evidence, ни в публичные ссылки | `test_fc_trust_retrieval.py::test_off_topic_candidates_do_not_reach_model_or_evidence`, `…typed_non_evidence_section` |
| 7 | 5.11, 5.12 | FCT-160, 161 | `-k numbers_and_causality` | иная единица/масштаб/период не подтверждает; корреляция не доказывает причинность | частично: `test_word_overlap_only_is_not_support_with_anchor_profile`, metrics-тесты планировщика |
| 8 | 5.13, 5.14, 5.15 | FCT-162, 163, 164; FCT-021; FCT-503 | `-k per_claim_coverage` | 4 из 6 частей → честный per-claim coverage и ограниченный вывод; одна опровергнутая часть ≠ `mixed`; две стороны → `mixed` с привязкой | `test_fc_trust_verdict.py::TestPartialIsNotMixed`, `TestExecutionStatus` (24 теста, negative control) |
| 9 | 5.16–5.21 | FCT-165, 166, 167, 168, 169, 170 | `-k "cascade or technical or dates or future or logical"` | уточнение находит первоисточник; каскад провайдеров и trace; падение/бюджет → технический статус, не `insufficient_evidence`; нет даты → `unknown`; будущее правило не выдаётся за состоявшееся; логика без фиктивной ссылки | `test_fc_trust_retrieval.py`: `test_provider_timeout_is_distinct_from_provider_error`, `test_rate_limit_is_distinct_from_provider_error`, `test_missing_date_is_unknown_and_never_invented`, `test_global_deadline_is_distinct_and_honest`, `test_cancelled_run_is_reported_as_cancelled` |
| 10 | 5.22, 5.23 | FCT-171, 172 | `-k "meme or reply_context"` | смысловая цель мема/Reply на комментарий без нового regex-триггера | `test_fc_trust_target.py::TestReferentialHint`, `test_factcheck_attribution_cfg06.py` |
| 11 | 5.25, 5.26, 5.27 | FCT-174, 175, 176; FCT-802/803/805 | `-k writer_live` и `-m live_provider`; для 5.27 — чтение `mca_bot_outputs` по `correlation_id` | даты один раз, unknown честно, `factcheck_prompts.py` sha256 `4cd1e893…`; настоящий провайдер на свежем утверждении; отправленный текст без ссылок вне EvidenceMap и без внутренних токенов | `test_fc_trust_s5_writer.py` (даты/unknown/канон), `test_fc_trust_render.py::TestNoInternalTokens`; **5.27 — только после реальной отправки** |
| 12 | 5.28, 5.29, 5.30 | FCT-177, 178, 179; FCT-180 | `-k "concurrent or injection or mutation"` + мутационный прогон Reviewer'а | два чата не делят evidence/кэш; malicious HTML/SSRF не меняет роль и доступы; мутация «неверный источник / подделанный supports / удалённая дата» меняет исход | `test_fc_trust_verdict.py::TestFCT1002ConcurrentChatsIsolation`, `tests/test_mca02_safe_fetch_round1027.py`, `tests/test_soul13_ssrf_guard_order.py`; мутацию делает Reviewer |

Процессные строки слайса (не сценарии): **FCT-140** и **FCT-180** закрываются самим фактом этого
артефакта — прогон на свежем кандидате с trace и текстом выхода, регресс direct/vision/summary/search
существующими наборами; **FCT-001** покрывается сценариями 6 и 3 (Миронов + тестостерон).
**FCT-179** требует мутационного прогона именно Reviewer'а (не Builder) — зафиксировано.

## 6. S8 — что нужно для релиза

| `req_id` | Требуется | Когда закрывается |
|---|---|---|
| FCT-220 | независимый replay Миронова (сценарий 8 + live) | до релиза |
| FCT-221 | ревью-подтверждение «лексика ≠ доказательство», «URL ≠ первоисточник», «raw search_text ≠ evidence» | до релиза (реквизит: сценарии 3, 5, 7) |
| FCT-222 | различение technical/refuted/conflict/logical/unknown во всех стадиях | до релиза (сценарии 8, 9 + render) |
| FCT-223 | живой E2E с действующими провайдерами и свежим утверждением | до релиза (частично после деплоя) |
| FCT-224 | отсутствие регрессий direct/vision/summary/search/команды/админка/стиль/QRNG/self-diag/память/истории/PG | кандидат + подтверждение на выложенном |
| FCT-225 | сверка старых FC/FCP-карт с deployed SHA | **только после деплоя** (D-S8-1) |
| FCT-226 | настройки владельца и промпты не изменены (хеши до/после) | до + после (пин `factcheck_prompts.py 4cd1e893…` уже в `deploy-2.58.271`) |
| FCT-227 | стандартные merge/review/deploy/health + краткий отчёт с коммитами, причиной, до/после | **после деплоя** |
| FCT-195 | негативные кейсы Reviewer + реальный провайдер DevOps + штатный деплой + отсутствие спама | **после деплоя** |
| FCT-196, 197, 198, 208 | процессные: гигиена артефактов, право Reviewer вернуть блокирующее, отсутствие лишних human gate, запрет DONE при моках/фиктивном вердикте/выключенном v2 | финальный аудит; FCT-208 напрямую зависит от FCT-316 |

Релизный конвейер не меняется: сборка на release-ветке → `requirements_gate.py --stage review
--slice … --candidate …` → независимое ревью точного SHA → `--stage deploy` → штатный деплой
(`git pull --ff-only` + restart на 192.255.209.205) → `--stage release --deployed-commit …` →
пост-проверки (identity/version/DDL/health/settings/prompts/effective flags) → отчёт.

## 7. Прогоны этого прохода

Base: detached worktree `3a78484b9` (release/2.58.271), Python из `.venv` репозитория.

| Команда | Результат | Сырой вывод |
|---|---|---|
| `pytest tests/test_fc_trust_retrieval.py -q -k "owner_param or owner_value or admin_config or limits_resolve"` | **7 passed, 63 deselected** | `raw/green-fct906-param-coverage.txt` |
| `pytest tests/test_evol_fc_admission.py tests/test_fc_trust_render.py -q` | **57 passed** | `raw/green-fct1001-904-adjacent.txt` |

Эти два прогона подтверждают только две вещи: (а) регистрация/эффективные значения лимитов фактчека
и честные дефолты уже покрыты тестами на выложенном SHA; (б) отказы/лимиты и отсутствие внутренних
токенов в публичном тексте покрыты. Они **не** заменяют приёмку S7 и не закрывают строки без
row-bound evidence.

## 8. Замечания по происхождению (важно для Orchestrator)

1. **Дубли `req_id` в источнике.** FCT-113 — 4 строки с идентичным текстом (10830–10833), FCT-011 —
   5 строк (4 items + 1 additional). Это не 4 и не 5 разных обязательств; закрывать нужно по одному
   фактическому требованию, но строки в карте остаются отдельными (историческая трассировка).
2. **master ≠ продуктовое дерево.** `d1b4334` не содержит ни `tests/test_fc_trust_*`, ни
   агрегатов S6-U2: продуктовые коммиты живут в `release/2.58.26x..271`. Любая проверка «на
   выложенном коде» обязана идти в worktree релиза, иначе тесты/файлы просто не найдутся.
3. **Evidence последних релизов на master отсутствует.** `release-2.58.265…271` содержат
   `plans/features/fc-trust-01/evidence/release-2.58.26x/` в ветках релизов, но не в master
   (в планировочном checkout есть только 257/259/263/264). Артефакты существуют и проверяемы
   (`git show release/2.58.271:…/deploy-2.58.271.md`), их не нужно создавать заново — нужно
   сослаться на них из S0/S8-артефакта.
4. **Устаревший finding.** `verification_findings.unregistered_admin_param`
   (`limits.factcheck_max_queries_total` не в каталоге) больше не соответствует коду: параметр
   зарегистрирован на `3a78484b9` (`services/param_catalog.py:2983`) с описанием влияния. FCT-906
   не требует нового кода каталога.
5. **Порядок статусов.** 8 строк S2 — `READY_FOR_LIVE` при выложенном коде (2.58.263); их evidence
   привязано к ревью-кандидату `70e03c97`, не к deployed SHA. Для закрытия нужен прогон на
   выложенном дереве, иначе доказательство остаётся «не к текущему SHA».

## 9. Предлагаемая дельта для `progress_scope.json` (сводка, не применено)

Текущее: `141 required → 40 VERIFIED / 15 REVIEW / 8 READY_FOR_LIVE / 78 PENDING` (101 открытая
строка, 92 distinct `req_id`).

Предлагаемые шаги (каждый — после своего доказательства, не пакетом):

| Шаг | Строки | Ожидаемая дельта |
|---|---|---|
| S0-артефакт (analysis + сверка карт + trace) | FCT-209×2, 211×2, 212, 214, 130, 137, 190, 131–136, 011×5, 010, 012 | 22 PENDING → VERIFIED (010/012 зависят от replay §5.1) |
| Связать уже зелёные прогоны §2 | FCT-906, FCT-317, FCT-1001, FCT-114 | 4 PENDING → REVIEW |
| S6-U3 (aggregate endpoint + панель + тесты секретов + дефолт флага) | FCT-901, 902, 903, 904, 905, 316, 194 | 4 REVIEW + 5 PENDING → 7 REVIEW / 2 READY_FOR_LIVE |
| Живой прогон S2 | FCT-022, 101–106, 701 | 8 READY_FOR_LIVE → VERIFIED |
| S5/ S4 live | FCT-802, 803, 805, 503, 504, 604, 1002 | 6 → VERIFIED |
| S7-приёмка | 35 строк | 34 → VERIFIED, FCT-176 → READY_FOR_LIVE |
| S8-релиз | 13 строк | 10 → VERIFIED, FCT-225/227/195 → VERIFIED после деплоя |
| FCT-113 ×4 | — | остаются REVIEW/PENDING до появления смыслового источника типа |
| FCT-192 | — | остаётся REVIEW до решения §10 п.2 |

## 10. Открытые решения (не Human Gate, а Architect/PM-развилки)

1. **FCT-113: источник `decision_status` / `normative_state_on_date`.** Нужен смысловой производитель
   (выход Analyst'а или envelope-подсказка), иначе контракт «четыре типа» наблюдаем только для
   двух. Это единственный разрыв, который нельзя закрыть приёмкой — нужен код.
2. **FCT-192: где доказывается семантическая оценка claim↔passage.** S4 исключил
   `relation_evidence.py`; строка осталась без владельца обязательства. Варианты: (а) признать
   существующий Analyst-выход источником и закрыть живым прогоном S7; (б) назначить отдельный шаг.
   Молчаливое «оставим REVIEW» недопустимо — эпик тогда не закрывается.
3. **FCT-903: `entity_collision` и `media_partial`.** Durable-сигнала нет; сейчас честный `None`.
   Решение: либо сохранять сигнал в run/evidence (аддитивно, +DDL), либо явно зафиксировать
   «не измеряется» как принятый контракт панели. Рекомендация: второе (bounded acceptance), с
   честной подписью в UI; первое — только если владелец потребует эти два счётчика.
4. **FCT-176: реальная отправка.** Либо изолированный тестовый чат, либо парковка
   `delivered_awaiting_evidence`. Блокером эпика не считать.

## 11. Честный итог

- Из 101 открытой строки **96 закрываются в этом контуре** (артефакт S0, S6-U3, живой прогон,
  S7-приёмка, штатный релиз) — 22 + 4 + 9 + 8 + 6 + 35 + 13, с пересечениями по FCT-316/194/223.
- **Недостижимы без нового кода: 4 строки** (`FCT-113` ×4) — нет производителя двух типов
  утверждения.
- **Недостижимы без решения: 1 строка** (`FCT-192`) — обязательство семантической оценки без
  владельца.
- **Недостижима без реальной отправки: 1 строка** (`FCT-176`) — честно паркуется после деплоя.
- Всё остальное — работа, а не ожидание: S6-U3 (9 строк + правило дефолта), S7-харнесс (35),
  S8-релиз (13), S0-артефакт (22).

## 12. Один следующий инженерный шаг

**S6-U3** — «панель/API агрегатов + effective-настройки + тесты секретов + заводской дефолт
`FACTCHECK_PIPELINE_V2_ENABLED = True`» на базе `3a78484b9`. Причины: это объявленная зависимость
S7 (`FCT-S7-ACCEPT depends_on FCT-S6-OBSERVABILITY`), он закрывает 9 строк, выполняет правило
проекта 09.11.2026 (без него FCT-208 запрещает DONE), а его write-scope (`web/api/routes.py`,
`web/app.js`, `services/param_catalog.py`, `config/settings.py`, новый
`tests/test_fc_trust_observability.py`) не пересекается с харнессом S7 — приёмочную матрицу можно
готовить параллельно read-only.

## 13. Что блокирует закрытие эпика

1. `FCT-113` — нет смыслового источника типа утверждения (нужен код).
2. `FCT-192` — обязательство семантической связки claim↔passage без владельца (нужно решение).
3. `FCT-316` — заводской дефолт v2-пути `False` при effective `true` (нужно код-изменение).
4. `FCT-901/903/194` — нет API/UI агрегатов (нужен S6-U3).
5. Отсутствие S7-харнесса — 35 строк нечем воспроизвести (нужен файл в write-scope S7).
6. `FCT-176` — единственная строка, где нужен реальный канал отправки; закрывается парковкой, не блокером.
