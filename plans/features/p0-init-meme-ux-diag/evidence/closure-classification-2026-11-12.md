# Классификация остатка эпика `p0-init-meme-ux-diag` (2026-11-12)

Автор: PM. Задача: `OI-2026-11-12-EXIT-CORRECTIVE-CYCLE` §1–§2, §6–§7.
Характер документа: **read-only классификация**. Здесь нет новых продуктовых требований, нет изменения
статусов, кода, карты или `progress_scope.json`. Всё, что похоже на изменение статуса, — **предложение**
(§11), которое применяет Orchestrator/PM после независимого ревью.

Источники, по которым сверялось (читались фактически):
`plans/features/p0-init-meme-ux-diag/requirements-map.json` (candidate_commit = deployed_commit = `6c11fc08`),
`slice-graph.json`, `architecture.md`, `release-258191..194/deploy.md`, `release-258194/live-*.json`,
`evidence/**` (r0, s2id, s3ov, s5b, S5M-MEME-DURABILITY, s6, s7accept), `plans/owner_inputs/2026-11-11-…excerpt.md`,
`plans/owner_inputs/2026-11-12-exit-corrective-cycle-initiative.md`, диффы `16cdb3b8` и `f2d3619d`,
`tools/requirements_gate.py` (release-гейт), прогоны тестов (см. §12).

---

## 0. Резюме

| Показатель | Значение |
|---|---|
| Обязательных строк карты (`items` + `additional_requirements`, кроме `disposition=context`) | **114** |
| Уникальных `req_id` | **77** |
| VERIFIED / REVIEW / PENDING / READY_FOR_LIVE (строки) | 63 / 25 / 24 / 2 |
| Открытых строк | **51** |
| Открытых уникальных требований | **37** (19 REVIEW, 16 PENDING, 2 READY_FOR_LIVE) |
| A `IN_CURRENT_FIXES` | **6 строк / 4 требования** |
| B `PROVEN_BIND_ONLY` | **23 строки / 20 требований** |
| C `REALLY_OPEN` | **22 строки / 13 требований** |
| D `FUTURE_EVENT` | **0 строк** |
| E `VOLUNTARY_OBSERVATION` | **0 строк** (1 добровольное наблюдение вне строк, §7) |

Три вывода, которые меняют картину «60/114»:

1. **Из двух кандидатов требования закрывает только один.** `16cdb3b8` не закрывает ни одной из 51 открытой
   строки: его строки (`P0IM-ID-FINISH`, `P0IM-ID-CONC`) уже стоят VERIFIED, а независимого ревью-артефакта
   у кандидата нет (§10.1). `f2d3619d` закрывает 6 строк (PB-VOCAB, PB-COUNT, PB-STEP, BAN-CONFLATE×3) и
   **не закрывает** заявленный `P0IM-PB-LLM`: дифф добавляет блок `llm` с `null` + причина, и собственный тест
   кандидата утверждает, что модель не записана (§10.2).
2. **Обязательных ожиданий «реального события» среди строк нет.** Ни 5%-жребий, ни ручной `/meme` не требуют
   живой прод-события: жребий проверяется управляемой конфигурацией (`test_probability_one_is_reported_as_no_draw`),
   ручной путь — изолированным вызовом обработчика (18 passed на выложенном `6c11fc08`, §7).
3. **Бухгалтерия гейта — не зелёная и не станет зелёной от объединения кандидатов.** Release-гейт на `6c11fc08`
   даёт `errors=216`: он требует, чтобы **у каждой** обязательной строки было evidence с `candidate_commit`,
   равным финальному кандидату, а для `live_required` — тип `live|production` на этом же кандидате. Значит
   в конечный объём входит перепривязка доказательств всех строк к финальному SHA (§8, шаг 5).

---

## 1. Знаменатель и дубликаты

- 132 строки всего, 18 — `disposition=context` (провенанс/границы), 114 обязательных, **77 уникальных**.
- 37 «лишних» строк — это 26 повторно используемых `req_id`. Самые крупные: `P0IM-OV-SAMPLE` — 5 строк с
  **одним и тем же** текстом приёмки; `P0IM-AC-SETTINGS` — 3 идентичных; `P0IM-AC-NODUP` — 3; `P0IM-BAN-CONFLATE` — 3.
- Вывод: **114 — корректная инвентаризация источника** (разные абзацы ТЗ, якоря строк сохранены), но как
  знаменатель прогресса она завышает вес повторяющихся пунктов. Для отчётности предлагается первичный
  знаменатель **77 уникальных** (сейчас 40/77 = 52%), а 114 — как построчный источник. Удалять строки нельзя.
- Шумовых (не несущих обязательства) строк среди 114 нет. Слабое место: `items[3]` (`P0IM-AC-NODUP`, L00006)
  опирается на строку «Kind: new_task … NOT a new product or a new diagnostic pipeline» — обязательство
  производное, но нормативное; дублирует `add[4]`/`add[71]`.
- `P0IM-AC-DONE` (`add[78]`) — не самостоятельное наблюдаемое требование, а **свёртка** критерия готовности
  (это же зафиксировано в `matrix-prod.json → rows_not_claimed`). Закрывается PM-сверткой, отдельной проверки не требует.

---

## 2. Что считается доказательством (границы категорий)

- **A** — поведение реализуется одним из двух текущих кандидатов; нужен независимый проход по объединённому
  кандидату, выкладка и привязка.
- **B** — поведение уже показано существующим артефактом (тест на выложенном `6c11fc08`, живой снимок,
  ранее одобренный кандидат) и требует только перепривязки к финальному кандидату/выложенному коммиту плюс
  подтверждения Reviewer. Обещание, план или чужое поведение за доказательство не принимались.
- **C** — наблюдаемого нет: либо не реализовано, либо не проверено; указаны точный пропуск и минимальное действие.
- **D** — обязательное требование, достижимое только реальным производственным событием.
- **E** — добровольное наблюдение вне обязательной инженерной приёмки.

Терминологическая оговорка: статус `REVIEW` в карте означает «доказательство есть, независимого подтверждения
нет». Поэтому REVIEW-строки попадают в **B**, если артефакт действительно демонстрирует пункт приёмки (тогда
работа = привязка + ревью), и в **C**, если артефакт демонстрирует не всё.

---

## 3. Все 51 открытая строка

Сокращения: `it` = `items`, `add` = `additional_requirements`. Кандидат B-строк — выложенный `6c11fc08` (2.58.194),
если не указано иное.

| # | row_ref | req_id | Срез | Статус | Кат. | Доказательство / точное следующее действие |
|---|---|---|---|---|---|---|
| 1 | it[3] | P0IM-AC-NODUP | S7 | PENDING | C | Нет независимого структурного аудита объединённого диффа (нет новых панелей/агентов/планировщиков/второго конвейера, нет логического хардкода). `release-258194/deploy.md §1` — заявление Builder (DDL=0, 53 файла), не аудит. → Reviewer (Architect при сомнении). |
| 2 | it[6] | P0IM-AC-SETTINGS | S7 | PENDING | C | Нет снимка prompt registry и сохранённых настроек до/после. → DevOps: снять существующим API/файлом регистр и настройки до и после выкладки объединённого кандидата; Reviewer сверяет. |
| 3 | it[20] | P0IM-MM-MARKER | S5 | REVIEW | B | `release-258193/deploy.md` (15 marker-тестов на релизной линии) + `release-258194/deploy.md §6(в)` (оба чата: `released`, `until` истёк, `expired=true`, полосы нет) + свежий прогон PM: 15 passed на `6c11fc08`. |
| 4 | it[21] | P0IM-OV-PERCHAT-CAUSE | S3 | REVIEW | B | `evidence/s3ov/binding-726736ee.md` O8/O1 (две подписанные колонки, без «это дефект») + `release-258194/live-modes-2.58.194.json` (режим «Другой чат» на обоих чатах, 6c11fc08) + `live-peek-2.58.194.json`. Reviewer: подтвердить, что compare-код не менялся после `726736ee`. |
| 5 | it[23] | P0IM-PB-LLM | S4 | PENDING | C | `f2d3619d` даёт только `llm={provider:null, model:null, slot:null, reason}`; `tests/test_initiative_publications_api.py::test_step_llm_fields_are_record_or_honest_null` это и утверждает. Нет провайдера/модели/слота, версий и источников промптов, реально отправленных messages. Нужно решение Архитектора (и, если требуется сузить пункт «фактически отправленные messages», — владельца): использовать существующий канал payload-наблюдаемости/`mca_events` для того, что он реально пишет, + `prompt_registry` для версий. |
| 6 | add[0] | P0IM-BAN-CONFLATE | S1 | PENDING | A | `f2d3619d`: счётчик `generated` + раздельные `checked/decided/generated/published/delivered/pending`. Тест `test_generated_is_not_considered_and_not_published` (PM: 78 passed в двух файлах API/диагностики). |
| 7 | add[4] | P0IM-AC-NODUP | S7 | PENDING | C | Как №1. |
| 8 | add[7] | P0IM-BAN-CONFLATE | S1 | PENDING | A | Как №6. |
| 9 | add[11] | P0IM-AC-UI-HOME | S7 | PENDING | B | Реальные экраны выложенной сборки (2.58.191–194), модуль в существующем разделе «Модули», компоненты/тёмная тема/адаптивность; `s7accept/matrix-prod.json` visual-замеры (1536×960, 390×844, `scrollWidth==clientWidth`). Reviewer: визуально подтвердить на финальной сборке, что новых страниц «ради страниц» нет. |
| 10 | add[14] | P0IM-S6-SCOPE | S6 | REVIEW | B | `release-258194/live-modes-2.58.194.json` + `live-peek-2.58.194.json` (payload своего чата, очистка карточек, штамп сервера) + тесты кандидата (`test_stale_response_for_another_chat_is_not_applicable`, `s6FreshSuite`, e2e `run_overview`) — `evidence/s6/binding-258194.md §5`. Reviewer: проверить валидность guard-тестов. |
| 11 | add[28] | P0IM-OV-L3 | S3 | REVIEW | B | `release-258193/live-overview-258193.png` (три разных факта + квота) + `evidence/s3ov/binding-726736ee.md` O4 + js-тест строки 365 (0 текста = без лимита / 0 мемов = предел) + живые счётчики 2.58.194. |
| 12 | add[29] | P0IM-OV-ACT | S3 | REVIEW | B | O7 + `tests/js/initiative_ui_rework_test.js:819` + `tests/ui_initiative_rework_e2e.py:1447` (переход в существующую диагностику этой попытки). Reviewer: подтвердить на выложенной сборке. |
| 13 | add[30] | P0IM-OV-COORD | S3 | REVIEW | B | O6 + js:742–763 (истёкший/живой/флаг сильнее срока) + `release-258194/deploy.md §6(в)` (полосы нет при истёкшем маркере). |
| 14 | add[31] | P0IM-OV-LIST | S3 | REVIEW | C | 5–10 строк есть (в кадре 5), но **метки manual/auto в строке нет** (сам live-артефакт это фиксирует), хотя `mode` уже есть в API. → Builder: показать источник попытки в строке; затем Reviewer. |
| 15 | add[33] | P0IM-OV-SAMPLE | S3 | REVIEW | C | Дословная/семантическая сверка образца на выложенной сборке не делалась (`binding-726736ee.md` прямо это фиксирует). → DevOps+Reviewer: снять обзор на финальной сборке и сверить 4 элемента; если расхождение только в формулировке — зафиксировать, что ТЗ требует «семантику образца», а не дословный текст (решение Reviewer, не PM). |
| 16 | add[34] | P0IM-OV-SAMPLE | S3 | REVIEW | C | Как №15 (строка «Мемы · Разрешено: ВКЛ \| Сейчас: пауза 33 мин»). |
| 17 | add[35] | P0IM-OV-SAMPLE | S3 | REVIEW | C | Как №15 (строка «Последний запуск: … изображение создано, отправка отложена»). |
| 18 | add[36] | P0IM-OV-SAMPLE | S3 | REVIEW | C | Как №15 (строка «Последняя подтверждённая отправка: … Telegram #1234»). |
| 19 | add[37] | P0IM-OV-SAMPLE | S3 | REVIEW | C | Как №15 (действие «Показать попытку»). |
| 20 | add[38] | P0IM-OV-SILENT | S3 | REVIEW | B | O4 + js:407/829/866 («бот решил промолчать» как работа, не OFF/сбой) + `ui_initiative_rework_e2e.py` (строка «бот решил промолчать»). |
| 21 | add[40] | P0IM-PB-FILTERS | S4 | PENDING | C | Фильтры/пагинация/поиск **реализованы** на `6c11fc08` (`chat/days/kind/mode/outcome/reason`, `limit/offset`, retention ≤90 дней) — `web/api/initiative_publications.py:682–760`, но живой проход их не нажимал, тесты покрывают 2 измерения из шести. → Reviewer/DevOps: прогнать фильтры и пагинацию на выложенной сборке, зафиксировать; отдельно решить, означает ли «поиск» свободный текст (сейчас это поиск по коду/ярлыку причины). |
| 22 | add[42] | P0IM-PB-STEP | S4 | PENDING | A | `f2d3619d`: `duration_ms`+`duration_reason` (честный null, не 0), `request_id`+`request_id_source`, блок `llm`. Тесты `test_step_carries_duration_or_reason_and_recorded_request_id`, `..._no_invented_request_id_for_historical_rows`. |
| 23 | add[44] | P0IM-PB-LLM | S4 | PENDING | C | Как №5 (дубль того же требования). |
| 24 | add[45] | P0IM-PB-MANUAL | S4 | PENDING | C | В ручной трассе есть права/команда/приоритет/бронь/отправка/результат (`INI_TRACE_STEPS.meme_manual`, 12 шагов), но **release и TTL маркера по попытке не показаны**; артефакта нет. → Builder: показать `claim.release`/`manual_priority_until` (поле пишется в `meme_initiative.py:4266`), либо доказать, что они уже видны, и зафиксировать. |
| 25 | add[46] | P0IM-PB-ACCESS | S4 | PENDING | C | Защищённого раскрытия полных текстов (RBAC + редактирование секретов + политика хранения + «исторически не сохранялось») нет вовсе; связано с решением по PB-LLM. Реализация/решение Архитектора. |
| 26 | add[48] | P0IM-PB-VOCAB | S4 | PENDING | A | `f2d3619d`: третье состояние `stale` + `stale_reason/age/window/basis`; остальные состояния уже были. Тест `test_stale_snapshot_is_not_no_data_and_needs_a_recorded_window` (PM: 1 passed). |
| 27 | add[49] | P0IM-PB-COUNT | S4 | PENDING | A | `f2d3619d`: `llm_calls`, `images`, `generated` в том же окне; `test_counts_carry_llm_calls_and_images_separately`. |
| 28 | add[51] | P0IM-BAN-CONFLATE | S1 | PENDING | A | Как №6. |
| 29 | add[56] | P0IM-A0-CONTRACT | A0 | PENDING | B | `architecture.md` — `DESIGN READY` (строка 60); `plan.md:74,145` и `slice-graph.json` (`design_ref`) ссылаются на него; контракт реализован (ID-CHILD/ID-FIELDS/MODE VERIFIED). Закрывается сверткой PM/Architect, кода не требует. |
| 30 | add[60] | P0IM-MM-TRACE | S5 | REVIEW | B | `tests/test_meme_command_autodelete.py` — 18 passed на `6c11fc08` (удаление команды первым сетевым действием, не-админ без ответа, отказ одной репликой, одна фотография без подписи) + `test_p0im_s5_meme_marker_interrupt.py` 15 passed + `test_p0_meme_publication_hotfix.py` 45 passed. Reviewer: подтвердить, что это покрывает «получение/регистрация/RBAC/удаление/приоритет/уведомление». |
| 31 | add[61] | P0IM-MM-PRIO | S5 | REVIEW | B | Marker-тесты: снятие на успехе/отказе/исключении/отмене, `release` не убивает второй маркер; `test_b1_interrupted_row_is_finalised_not_resent` (durable-восстановление существующим механизмом); `test_manual_new_messages_do_not_cancel_ready_meme`. |
| 32 | add[62] | P0IM-MM-PRIO | S5 | REVIEW | B | Как №31. |
| 33 | add[63] | P0IM-MM-DEFER | S5 | REVIEW | B | `test_automatic_reports_real_conflict_before_generation`, `test_automatic_collision_after_generation_keeps_facts_and_does_not_send` + показ «ждёт» с причиной (O1/O4). |
| 34 | add[64] | P0IM-MM-SECRET | S5 | REVIEW | B | `s7accept/matrix-prod.json`: 403 не-админу, 422 без чата, нет смешения чатов; autodelete: не-админ — тишина; промпты в Telegram не публикуются (отправляется только фото без подписи). |
| 35 | add[65] | P0IM-S6-EFFECTIVE | S6 | REVIEW | C | Реальный недобор (`evidence/s6/binding-258194.md §4`): в живом payload 4 гейта из 5 (нет `image_module`), `heartbeat` и провайдеры не отражены, у второго чата слои не отрендерены, нет до/после-снимка сохранённых настроек. → Builder (если гейт обязан быть в ответе) + DevOps (сверка effective-значений image_module/heartbeat/провайдеров существующими поверхностями) + Reviewer. |
| 36 | add[66] | P0IM-S6-SCOPE | S6 | REVIEW | B | Как №10 (дубль). |
| 37 | add[70] | P0IM-AC-UI-HOME | S7 | PENDING | B | Как №9. |
| 38 | add[71] | P0IM-AC-NODUP | S7 | PENDING | C | Как №1. |
| 39 | add[73] | P0IM-AC-MATRIX-CONFIG | S7 | REVIEW | C | Матрица: 12 проверок passed; не покрыты два пункта строки: «100% вероятности, когда жребий не нужен» (есть тест `test_probability_one_is_reported_as_no_draw`, `test_meme_init_diagnostics.py`) и «отсутствие повода у L1» (observer `l1_silent` + OV-SILENT). → добавить 2 проверки в матрицу (или привязать эти тесты) и прогнать на финальном кандидате. |
| 40 | add[74] | P0IM-AC-MATRIX-FAIL | S7 | REVIEW | C | Не покрыты: ранние гейты без `job_id` (есть `test_early_refusal_has_its_own_run_id`, `test_cooldown_quota_quiet_refusals_carry_run_id`), конфликт отправок (есть hotfix + ID-CONC), старые неполные записи (есть). **Нет тестов/проверок** на «обрыв после LLM A/B» и «пустое изображение». → 2 новых теста + привязка 3 существующих. |
| 41 | add[75] | P0IM-AC-MATRIX-MANUAL | S7 | PENDING | B | `test_manual_run_bypasses_quota_cooldown_and_closed_gate` (PM: 18 passed на `6c11fc08`) — ручной запуск при исчерпанной квоте; автопопытка откладывается с причиной (`test_automatic_reports_real_conflict_before_generation`); истечение TTL (`deploy.md §6(в)` + `AC-EXPIRED-NOT-BUSY`). Живой ручной `/meme` **не требуется** (§7). |
| 42 | add[76] | P0IM-AC-MATRIX-RBAC | S7 | REVIEW | C | Матрица: 403/422/нет смешения чатов passed. Не покрыты: скан полной трассы на утечку секретов (исполнимо Reviewer'ом на выложенном эндпоинте — читать payload и искать ключи/токены) и конкурирующие держатели (есть `P0IM-ID-CONC`). → скан + привязка. |
| 43 | add[77] | P0IM-AC-MATRIX-UI | S7 | REVIEW | B | Матрица: 4 проверки + 11 скриншотов (1536/390, гонка 2.4 с, чужой `chat_id`, истёкший маркер). Остаток — собственные контрпримеры Reviewer (это акт ревью) и реальный TMA-хост (ограничение среды, не acceptance, по `binding-992f45ab.md §4`). |
| 44 | add[78] | P0IM-AC-DONE | S7 | PENDING | C | Свёртка критерия готовности; закрывается PM после VERIFIED остальных строк. Отдельной проверки не требует. |
| 45 | add[79] | P0IM-AC-SETTINGS | S7 | PENDING | C | Как №2. |
| 46 | add[80] | P0IM-AC-ORDER | S7 | PENDING | B | Порядок соблюдён: `evidence/r0/diagnosis-2.58.188.md` (read-only фактчек на `c087253d`) → 2.58.191–194. Фиксирует PM/Reviewer сверткой. |
| 47 | add[81] | P0IM-AC-POLICY | S7 | PENDING | B | Функция включена (`configuration.enabled=true` в живых ответах обоих чатов), OFF/SHADOW нет, лимитов не добавлено (`deploy.md §1`: DDL=0, новых флагов/настроек нет). Reviewer подтверждает effective-state на финальной сборке. |
| 48 | add[82] | P0IM-AC-SETTINGS | S7 | PENDING | C | Как №2. |
| 49 | add[84] | P0IM-AC-POSTREL | S7 | REVIEW | B | Скриншоты двух чатов (обзор/трасса/счётчики) в `s7accept/visual/ac-postrel-*` (2.58.194), артефакты реальной доставки (`9e6da9ef…`/`mca_bot_outputs 1620`/`11107`), статус прода (`deploy.md §4–5`). Остаток — независимый вердикт Reviewer, он и будет артефактом объединённого ревью. |
| 50 | add[85] | P0IM-S5B-NODISCARD | S5b | READY_FOR_LIVE | B | `evidence/s5b/binding-e92cdcd5.md`: независимая проверка Reviewer на изолированном worktree с фейковым отправителем (строка `queued`, равенство байтов и sha256, `journal preserved=true`, `delivery=not_sent`, ветка `preserved=false` с причиной, восстановление после перезапуска ровно одной отправкой, истечение срока без отправок) + живой `not_delivered` с причиной. Живой `defer→delivered` — добровольное наблюдение (§7). |
| 51 | add[87] | P0IM-S5B-QUOTA | S5b | READY_FOR_LIVE | B | Живой read-model `6c11fc08`: `spent 3/3`, `delivered 2`, `not_delivered 1`, `publisher_not_bound`, экран «израсходовано без отправки: 1 (отправитель не привязан)»; тестовая половина e92cdcd5. Счётчики попытки/изображения/отправки не слиты. |

---

## 4. Категория A — что именно делают кандидаты

Проверено по фактическим диффам (`git show --stat`/`show`), не по описанию.

**`16cdb3b8`** — `services/meme_initiative.py` (+117/−14) и `tests/test_evol014_meme_initiative.py` (+274):
`_spool_payload`, удержание строки в `self._unpersisted` (потолок 200), полный JSON в ERROR, `_retry_unpersisted`
с переносом ровно один раз. **Среди 51 открытой строки он не покрывает ни одной**: его строки
(`P0IM-ID-FINISH`, `P0IM-ID-CONC`) уже VERIFIED.

**`f2d3619d`** — 9 файлов (+990/−18): `services/initiative_diagnostics.py`, `web/api/initiative_publications.py`,
`web/app.js`, `web/index.html`, `web/static/app.css`, тесты. Покрывает:

| Строки | Что добавлено | Артефакт/тест (проверено) |
|---|---|---|
| PB-VOCAB (add[48]) | `data_state=stale` + `stale/stale_reason/stale_age_seconds/stale_window_seconds/stale_window_basis`, окно только из записи | `test_stale_snapshot_is_not_no_data_and_needs_a_recorded_window` — PM: **1 passed** |
| PB-COUNT (add[49]) | `llm_calls`, `images` в счётчиках того же окна | `test_counts_carry_llm_calls_and_images_separately` |
| PB-STEP (add[42]) | `duration_ms`/`duration_reason`, `request_id`/`request_id_source` | `test_step_carries_duration_...`, `test_step_has_no_invented_request_id_for_historical_rows` |
| BAN-CONFLATE (add[0],add[7],add[51]) | счётчик `generated` (журнал дошёл до `publish`) | `test_generated_is_not_considered_and_not_published` |
| — (не закрывает) | PB-LLM: только `llm={null…, reason}` | `test_step_llm_fields_are_record_or_honest_null` утверждает, что модель **не** записана |

Мои прогоны (PM, только чтение, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`):
- `f2d3619d`: `tests/test_initiative_publications_api.py` + `tests/test_meme_init_diagnostics.py` → **78 passed**;
  `node tests/js/initiative_ui_rework_test.js` → **INITIATIVE-UI-OK**.
- Совместимость кандидатов: `git merge-tree --write-tree 16cdb3b8 f2d3619d` → дерево `1dea083f`, **конфликтов 0**
  (файловые наборы не пересекаются), т.е. требование владельца «один согласованный кандидат» технически выполнимо.

**Чего у кандидатов нет (важно для планирования):** ни у `16cdb3b8`, ни у `f2d3619d` нет evidence-привязки
`plans/features/.../evidence/**` и нет независимого ревью-артефакта. `f2d3619d` вообще не упомянут в карте.

---

## 5. Категория B — 23 строки, закрываемые привязкой (без нового кода)

`it[20] MM-MARKER`, `it[21] OV-PERCHAT-CAUSE`, `add[11]/add[70] AC-UI-HOME`, `add[14]/add[66] S6-SCOPE`,
`add[28] OV-L3`, `add[29] OV-ACT`, `add[30] OV-COORD`, `add[38] OV-SILENT`, `add[56] A0-CONTRACT`,
`add[60] MM-TRACE`, `add[61]/add[62] MM-PRIO`, `add[63] MM-DEFER`, `add[64] MM-SECRET`,
`add[75] AC-MATRIX-MANUAL`, `add[77] AC-MATRIX-UI`, `add[80] AC-ORDER`, `add[81] AC-POLICY`,
`add[84] AC-POSTREL`, `add[85] S5B-NODISCARD`, `add[87] S5B-QUOTA`.

Для каждой: артефакт и кандидат — в таблице §3 и в машинном блоке §11. Общее требование: **привязка к финальному
кандидату + независимое подтверждение Reviewer** (в карте нет ни одного отдельного ревью-артефакта, §10.1).
Отдельно: `AC-MATRIX-MANUAL` и `S5B-*` закрываются тестами/живыми снимками, а не живым ручным запуском.

---

## 6. Категория C — 22 строки, где нужна работа или проверка

| Строки | Точный пропуск | Минимальное действие | Роль |
|---|---|---|---|
| AC-NODUP (it[3], add[4], add[71]) | нет независимого аудита «нет новых систем/панелей/второго конвейера/хардкода» | аудит объединённого диффа от `6c11fc08`, короткая запись в evidence | Reviewer (+Architect при сомнении) |
| AC-SETTINGS (it[6], add[79], add[82]) | нет до/после-снимка prompt registry и сохранённых настроек | снять существующим API/файлом до и после выкладки | DevOps + Reviewer |
| PB-LLM (it[23], add[44]) | нет провайдера/модели/слота/версий промптов/реальных messages | решение Архитектора: использовать существующий payload-канал + registry; при необходимости сузить пункт «messages» решением владельца | Architect (+владелец) |
| PB-ACCESS (add[46]) | нет защищённого раскрытия полных текстов, редактирования секретов, политики хранения | реализовать на существующем store, либо зафиксировать невозможность и решение | Architect + Builder |
| PB-MANUAL (add[45]) | нет `release`/TTL маркера по попытке | показать в шаге брони, либо доказать, что видны | Builder → Reviewer |
| OV-LIST (add[31]) | нет метки manual/auto в строке журнала | добавить источник попытки (поле уже в API) | Builder |
| OV-SAMPLE (add[33..37]) | нет сверки семантики образца на выложенной сборке | снять обзор и сверить 4 элемента; зафиксировать трактовку «семантика, не дословно» | DevOps + Reviewer |
| PB-FILTERS (add[40]) | фильтры/пагинация/поиск не нажимались; тесты покрывают 2 из 6 измерений | прогнать фильтры на выложенной сборке; уточнить смысл «поиска» | Reviewer/Builder |
| S6-EFFECTIVE (add[65]) | 4 из 5 гейтов, нет heartbeat/провайдеров, второй чат без слоёв, нет снимка настроек | добавить недостающий гейт в ответ (если обязан) + сверить effective-значения существующими поверхностями | Builder + DevOps |
| AC-MATRIX-CONFIG (add[73]) | не покрыты «100% вероятности» и «нет повода у L1» | 2 проверки в матрицу или привязка 2 существующих тестов | Reviewer/Builder |
| AC-MATRIX-FAIL (add[74]) | нет «обрыв после LLM A/B» и «пустое изображение»; 3 пункта без привязки | 2 теста + привязка 3 существующих | Builder + Reviewer |
| AC-MATRIX-RBAC (add[76]) | нет скана трассы на секреты; конкуренты без привязки | скан payload на ключи/токены + привязка ID-CONC | Reviewer |
| AC-DONE (add[78]) | свёртка, не наблюдаемое | свертка после остальных | PM |

---

## 7. D/E: почему обязательных «реальных событий» нет

1. **5%-жребий.** Отдельной строки в карте нет; фраза источника «100% вероятности, когда жребий не нужен»
   относится к `P0IM-AC-MATRIX-CONFIG` и проверяется **управляемой конфигурацией**: `trigger_probability=1.0`
   → `draw` не выполняется (`tests/test_meme_init_diagnostics.py::test_probability_one_is_reported_as_no_draw`),
   а промах жребия как ожидание уже покрыт живой строкой (`probability 0.05, hit=true` в `binding-992f45ab.md §1`)
   и `test_axis_readiness_has_no_invented_eta_after_lottery_miss`. **Ждать естественный 5% не нужно.**
2. **Ручной `/meme`.** Контракт требует «независимую проверку» ручного запуска при исчерпанной квоте
   (источник §8/§134) и отдельно — «проверить через работающий production-процесс» лишь в §1 для read-only
   диагностики. Владелец 2026-11-12 §6 прямо предписал: доказать доступными средствами (интеграционные тесты,
   управляемая случайность, изолированный вызов обработчика), **не выполнять команду от его имени**, не отправлять
   сообщения в живые чаты. Поэтому:
   - обязательная часть доказана на выложенном `6c11fc08`: 18 passed в `tests/test_meme_command_autodelete.py`,
     включая `test_manual_run_bypasses_quota_cooldown_and_closed_gate`, `test_non_admin_gets_silence_...`,
     `test_admin_delete_is_first_network_action_...`; 72 passed в связке hotfix+marker+binding-delivery;
   - «живой ручной запуск когда-нибудь» — **добровольное наблюдение**, не требование и не поручение владельцу.
3. **Единственное настоящее будущее событие** — `WO-258194-S5B-DEFERRED` (`publisher_not_bound → отложено →
   доставлено на живом тике`, зарегистрировано в `waiting_observations`). Оно **не является acceptance-строкой**:
   обе строки S5b доказаны тестами с фейковым отправителем (`binding-e92cdcd5.md`) и живым `not_delivered` с причиной.
   Это пост-релизное наблюдение агентов (тип E), не блокер закрытия и не процент.

Итог: **D = 0 строк, E = 0 строк**; одно добровольное наблюдение (`WO-258194-S5B-DEFERRED`) остаётся открытым
как наблюдение и не входит в знаменатель.

---

## 8. Конечное условие DONE (полный список)

1. **Закрыть 37 открытых уникальных требований**: 4 — кандидатом `f2d3619d` (A), 20 — привязкой существующих
   доказательств (B), 13 — работой/проверкой (C).
2. **Восстановить независимость ревью по durable-артефактам**: `P0IM-ID-FINISH`, `P0IM-ID-CONC` стоят VERIFIED
   на `16cdb3b8`, у которого ревью-артефакта нет. Либо Reviewer оформляет вердикт на объединённом кандидате,
   либо строки переводятся в REVIEW до него (§10.1). Это исправление привязки, не переделка работы.
3. **Один согласованный кандидат** (16cdb3b8 + f2d3619d, merge чистый) — независимое ревью по трём опорам
   (реализация, валидность тестов, собственный контрпример) по списку §9; артефакт ревью обязан быть файлом
   в `plans/features/p0-init-meme-ux-diag/evidence/`.
4. **Одна выкладка** объединённого кандидата с обязательными тестами, проверкой effective-конфигурации,
   снимком БД и rollback; после — живые постдеплой-проверки (обзор/история/трасса/счётчики/квота, оба чата).
5. **Перепривязка evidence всех обязательных строк** к финальному `deployed_commit` с типом `live|production`
   для `live_required` строк — иначе `requirements_gate.py --stage release` не может быть зелёным
   (сейчас `errors=216`, §10.6). Это бухгалтерия, но она входит в DONE по контракту проекта.
6. **Зелёный release-гейт** на фактический кандидат/деплой (или каждый остающийся error доказанно канцелярский
   и исправлен).
7. **Нет блокирующих находок**; всё некритичное — один раз в `plans/backlog.md` с доказательством.
8. **Свертка**: карта (строки+статусы+evidence), `slice_progress`, `epic_totals`, `waiting_observations`
   (только добровольное наблюдение S5b), `progress_scope.json`/очередь — силами Orchestrator/PM.
9. `P0IM-AC-DONE` закрывается как свёртка после п.1–8.

Порядок исполнения: `docs/evidence` интеграция веток (см. §10.5) → объединённый кандидат → Reviewer → выкладка →
живые проверки → перепривязка + гейт → свертка → очередь (`self-diag-01`, `vmq-onto-01`).

---

## 9. Что обязан проверить независимый Reviewer на объединённом кандидате

Кандидат: merge `16cdb3b8` + `f2d3619d` (база `6c11fc08`; `merge-tree` = дерево `1dea083f`, конфликтов нет).

1. **Durability (16cdb3b8)** — `P0IM-ID-FINISH`, `P0IM-ID-CONC`:
   - удержание строки, перенос **ровно один раз** (повтор `attempt_id` = no-op), полный JSON без усечения,
     потолок 200 с полной записью вытесненной строки;
   - что read-model не выдаёт старую попытку за «последнюю», пока строка удержана;
   - валидность 6 новых тестов и 3 мутаций; отсутствие регрессий в серии 15 файлов;
   - собственный контрпример: смерть процесса при удержанной строке (принятое окно `RW-D4-BOTH-WRITE-FAIL` —
     проверить, что оно действительно только логируется и не маскируется).
2. **Trace/счётчики (f2d3619d)** — `PB-VOCAB`, `PB-COUNT`, `PB-STEP`, `BAN-CONFLATE`:
   - инверсия `stale` ↔ `no_data` невозможна; окно берётся только из записи, нет окна → `window_not_recorded`;
   - `llm_calls`/`images` не считают чужие этапы дважды; `generated` ≠ published ≠ delivered; `considered` не публикация;
   - `request_id` не выдуман для исторических строк; `duration_ms=null` с причиной, не 0;
   - `llm`-блок не подставляет модель из текущих настроек (и не выдаётся за доказательство PB-LLM).
3. **Совместимость двух кандидатов**: строки, которые пишет `16cdb3b8` (в т.ч. перенесённые позже), должны давать
   этап `publish` и попадать в `generated`/счётчики; отложенный перенос не должен ломать группировку попытки.
4. **Регрессии уже VERIFIED строк**: `f2d3619d` правит `web/app.js`/`index.html` — проверить, что
   `P0IM-OV-HONEST-LINE`, `P0IM-OV-HONEST-UNAVAIL`, `P0IM-PB-TRACE`, `P0IM-PB-ROW`, `P0IM-OV-CARDS`, `P0IM-S6-EXPIRED`
   не сломаны (иначе их VERIFIED подлежит переоткрытию).
5. **Применимость ранее подтверждённых доказательств** (S3-OV, S5-MEME, S5b, S6, S7) к финальному дереву:
   какие блоб-идентичны, какие перепроверены, какие требуют новой привязки.
6. **Пункты, которые карта ошибочно считает сделанными**: PB-LLM (только honest-null), PB-MANUAL (нет release/TTL),
   OV-LIST (нет manual/auto), S6-EFFECTIVE (нет image_module/heartbeat/провайдеров) — ревью должно подтвердить
   C-статус, а не закрыть их по описанию кандидата.
7. Собственный риск-ориентированный контрпример Reviewer (не из набора Builder) на самый опасный шов:
   журнал/спул/read-model + аддитивные поля ответа.

---

## 10. Аномалии (не молчать)

### 10.1 Завышенные статусы и отсутствующие ревью-артефакты
1. **Ни у одного кандидата эпика нет отдельного durable-артефакта независимого ревью.** Привязки
   (`s3ov/binding-726736ee.md`, `s7accept/binding-*.md`, `s5b/binding-e92cdcd5.md`, `s6/binding-258194.md`)
   честно пишут, что это **PM-привязка** и цитаты наблюдений Reviewer, переданных оркестратором. Это объясняет,
   почему статусы держатся в REVIEW.
2. **`16cdb3b8` — худший случай:** ревью-артефакта нет вообще, но карта (`slice_progress.S2-ID`), `residual_windows.RW-D4`
   и `defect_classification.D4` утверждают «одобрен независимым Reviewer», а строки `P0IM-ID-FINISH` (it[17], add[57])
   и `P0IM-ID-CONC` (add[59]) стоят **VERIFIED**. По правилам приёмки это **завышение**: до ревью объединённого
   кандидата корректный статус — REVIEW (кандидат одобрен-де-факто, но не подтверждён артефактом).
3. **`f2d3619d` не отражён в карте вообще** (нет строки, нет evidence, нет ревью), хотя закрывает 6 строк.
   Заявление «f2d3619d покрывает P0IM-PB-LLM» **неверно** (см. §4, §10.2).

### 10.2 Устаревшие/неверные формулировки в самой карте
- `recorded_limits.S4TRACE-NO-LLM-IMAGE-ATTEMPT-AFTER-DEPLOY`: «код её выводит» про связку
  провайдер/модель/версии промптов/реальные messages — **неверно на `6c11fc08`**: в трассе нет ни модели,
  ни версий промптов, ни messages; `f2d3619d` добавляет только честный `null`.
- `recorded_limits.S3OV-COMPARE-READS-OTHER-CHAT`: «на проде этот режим не открывался» — **устарело**:
  `release-258194/live-modes-2.58.194.json` содержит `other_mode` для обоих чатов на `6c11fc08`.
  Не открывался только режим «Сравнить чаты».
- `recorded_limits.S4TRACE-NO-MANUAL-ATTEMPT-AFTER-DEPLOY` и `S5MEME-NO-MANUAL-RUN-AFTER-258193` описывают
  отсутствие живого ручного запуска как недобор; после `OI-2026-11-12 §6` это **не недобор**, а снятое требование
  (см. §7). Формулировки надо привести к новому основанию, иначе они будут вечно держать строки в ожидании.

### 10.3 Целостность путей доказательств (проверено по Git-деревьям)
- `evidence/s7accept/run/result.json` и `run/SUMMARY.md` (на них ссылается `matrix-prod.json → meta.json_path/summary_path`)
  **не существуют ни в одном проверенном дереве** — висячий указатель. Заменить на `matrix-prod.json`/`matrix-prod.md`.
- `evidence/s7accept/visual/**` (11 скриншотов + `visual-measurements.json`) и `prod-snapshot-2.58.194.json`
  существуют **только в ветке `init/meme-s7-accept` (`8d2553ed`)**, отсутствуют и в `master`, и в выложенном
  `6c11fc08`. Пока не интегрированы — доказательства S7 не durable.
- `evidence/S3-OV/*.png` и `evidence/s5b/playwright-visual.json|*.png` существуют **только на релизной линии**
  (`6c11fc08`), в `master` их нет; карта на `master` на них ссылается.
- Обратная проблема: `evidence/s6/binding-258194.md`, `evidence/s3ov/*`, `evidence/s2id/*`,
  `evidence/S5M-MEME-DURABILITY/*`, `evidence/r0/*`, `evidence/s7accept/binding-992f45ab.md` есть **только в `master`**,
  в `release/2.58.194` их нет. Код и доказательства живут в разных ветках.
- **Регистр каталогов:** `evidence/s3ov/` (master, привязки) и `evidence/S3-OV/` (релизная линия, скриншоты) —
  на Linux (production) это **два разных каталога**. Карта цитирует оба написания; при интеграции пути
  `S3-OV/overview-filled-*.png` и `s3ov/binding-*.md` обязаны существовать с согласованным регистром.
- В `evidence/s5b/binding-e92cdcd5.md` часть путей (`playwright-visual.json`, скриншоты) была **снята** как
  неразрешимая в `master`; сами файлы есть на релизной линии. После интеграции путь нужно вернуть.

### 10.4 Знаменатель
114 строк корректны как инвентаризация, но 37 строк — повторы 26 `req_id` (5×OV-SAMPLE с одним текстом приёмки,
3×AC-SETTINGS с идентичным текстом). Для прогресса предлагается **77 уникальных**, 114 — детализация.
`P0IM-AC-DONE` — свёртка, не отдельное наблюдаемое.

### 10.5 Ветки/линия
`master` (текущий корень) не содержит модуля «Инициатива/Мемы», выложенный `6c11fc08` — содержит. До интеграции
release-линии в канонический корень ни карта (`master`), ни код (release) не дают целостной картины; любые
проверки целостности путей будут красными по построению.

### 10.6 Гейт
`evidence/s7accept/gate-plan-6c11fc08.txt`: `stage=plan ... errors=0` (плановая стадия проходила).
`evidence/s7accept/gate-release-6c11fc08.txt` — `errors=205`; мой повторный read-only прогон на текущей карте
(`--stage release --candidate 6c11fc08 --deployed-commit 6c11fc08`) даёт `errors=216`, `scoped=114`. Причина — не
продукт: release-стадия требует **у каждой** строки evidence с `candidate_commit == candidate` и, для
`live_required`, тип `live|production` на этом кандидате; сейчас большинство строк привязано к прошлым кандидатам
(`bcc090a3`, `726736ee`, `7a7cd0ce`). Это и есть конечная перепривязка из §8 п.5.

---

## 11. Предлагаемая дельта привязки (только предложения; не применено)

Правила блока:
- `status_after_review_proposal` — статус, который **предлагается** после независимого ревью и привязки, а не сейчас.
- `candidate_commit` — коммит, к которому предлагается привязать. `""` = артефакт ещё должен быть создан на
  объединённом кандидате (его SHA появится после merge; сейчас есть только merge-tree `1dea083f`).
- `basis` — чем именно подтверждается пункт (коротко, без новых обещаний).

```json
{
  "schema": "p0im-closure-classification/1",
  "epic": "p0-init-meme-ux-diag",
  "as_of": "2026-11-12",
  "source_map": "plans/features/p0-init-meme-ux-diag/requirements-map.json",
  "source_map_sha256_note": "map not re-hashed here; Orchestrator must re-run the gate after edits",
  "denominator": {"rows_mandatory": 114, "unique_req_ids": 77, "open_rows": 51, "open_unique": 37,
                  "proposed_progress_denominator": 77},
  "counts": {"A_IN_CURRENT_FIXES": 6, "B_PROVEN_BIND_ONLY": 23, "C_REALLY_OPEN": 22,
             "D_FUTURE_EVENT": 0, "E_VOLUNTARY_OBSERVATION": 0},
  "bindings": [
    {"req_id": "P0IM-BAN-CONFLATE", "row_ref": "add[0]", "category": "A", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s4trace/binding-f2d3619d.md", "candidate_commit": "",
     "basis": "f2d3619d: counters.generated + separate checked/decided/generated/published/delivered/pending; test_generated_is_not_considered_and_not_published"},
    {"req_id": "P0IM-BAN-CONFLATE", "row_ref": "add[7]", "category": "A", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s4trace/binding-f2d3619d.md", "candidate_commit": "",
     "basis": "same as add[0]"},
    {"req_id": "P0IM-BAN-CONFLATE", "row_ref": "add[51]", "category": "A", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s4trace/binding-f2d3619d.md", "candidate_commit": "",
     "basis": "same as add[0]"},
    {"req_id": "P0IM-PB-STEP", "row_ref": "add[42]", "category": "A", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s4trace/binding-f2d3619d.md", "candidate_commit": "",
     "basis": "duration_ms/duration_reason + request_id/request_id_source + llm block; tests test_step_carries_duration_or_reason_and_recorded_request_id, test_step_has_no_invented_request_id_for_historical_rows"},
    {"req_id": "P0IM-PB-VOCAB", "row_ref": "add[48]", "category": "A", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s4trace/binding-f2d3619d.md", "candidate_commit": "",
     "basis": "data_state=stale + stale_* fields, window only from record; test_stale_snapshot_is_not_no_data_and_needs_a_recorded_window"},
    {"req_id": "P0IM-PB-COUNT", "row_ref": "add[49]", "category": "A", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s4trace/binding-f2d3619d.md", "candidate_commit": "",
     "basis": "llm_calls/images in same window; test_counts_carry_llm_calls_and_images_separately"},

    {"req_id": "P0IM-MM-MARKER", "row_ref": "items[20]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/release-258194/deploy.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "live §6(в): both chats released, until expired, expired=true, no coordination band; marker suite 15 passed on the release line (PM re-run at 6c11fc08)"},
    {"req_id": "P0IM-OV-PERCHAT-CAUSE", "row_ref": "items[21]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s3ov/binding-726736ee.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "O8/O1 (two labelled columns, no defect verdict) + live-modes-2.58.194.json other_mode on both chats; Reviewer must confirm compare code unchanged since 726736ee"},
    {"req_id": "P0IM-AC-UI-HOME", "row_ref": "add[11]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s7accept/matrix-prod.json", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "visual measurements 1536x960/390x844 on deployed build, module inside existing Modules section; Reviewer visual confirm"},
    {"req_id": "P0IM-AC-UI-HOME", "row_ref": "add[70]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s7accept/matrix-prod.json", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "same as add[11]"},
    {"req_id": "P0IM-S6-SCOPE", "row_ref": "add[14]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s6/binding-258194.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "live modes/peek (own payload, card cleared, server stamp) + candidate guard tests; Reviewer validates guard assertions"},
    {"req_id": "P0IM-S6-SCOPE", "row_ref": "add[66]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s6/binding-258194.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "same as add[14]"},
    {"req_id": "P0IM-OV-L3", "row_ref": "add[28]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/release-258193/live-overview-258193.png", "candidate_commit": "7a7cd0ce959a320cef1c70a76a4483ffe5817d9a",
     "basis": "three separate facts + quota line; 0-text=no-limit vs 0-meme=limit asserted in js test line 365; live counters at 6c11fc08 confirm same UI"},
    {"req_id": "P0IM-OV-ACT", "row_ref": "add[29]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s3ov/binding-726736ee.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "O7 + js:819 + e2e:1447 (jump into existing diagnostics of that attempt, absent without parent)"},
    {"req_id": "P0IM-OV-COORD", "row_ref": "add[30]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s3ov/binding-726736ee.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "O6 + js:742-763 (expired/live/flag-over-time) + live no band with expired marker"},
    {"req_id": "P0IM-OV-SILENT", "row_ref": "add[38]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s3ov/binding-726736ee.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "O4 + js:407/829/866 ('bot chose to stay silent' as working, not OFF/fault)"},
    {"req_id": "P0IM-A0-CONTRACT", "row_ref": "add[56]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/architecture.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "DESIGN READY (line 60), plan.md:74/145 and slice-graph design_ref point to it; contract rows ID-CHILD/ID-FIELDS/MODE verified"},
    {"req_id": "P0IM-MM-TRACE", "row_ref": "add[60]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/release-258194/deploy.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "PM re-run at 6c11fc08: test_meme_command_autodelete.py 18 passed (delete-first, non-admin silence, refusal, one photo), marker suite 15 passed; trace dict meme_manual exists"},
    {"req_id": "P0IM-MM-PRIO", "row_ref": "add[61]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/release-258194/deploy.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "marker cleared on success/refusal/exception/cancel; release keeps a second marker; interrupted row finalised not resent"},
    {"req_id": "P0IM-MM-PRIO", "row_ref": "add[62]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/release-258194/deploy.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "same as add[61]"},
    {"req_id": "P0IM-MM-DEFER", "row_ref": "add[63]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/release-258194/deploy.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "hotfix tests: real conflict before generation, collision after generation keeps facts and does not send; UI shows waiting with reason"},
    {"req_id": "P0IM-MM-SECRET", "row_ref": "add[64]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s7accept/matrix-prod.json", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "403 non-admin, 422 without chat, no cross-chat mixing; autodelete: non-admin silence; only photo without caption (no prompts in Telegram)"},
    {"req_id": "P0IM-AC-MATRIX-MANUAL", "row_ref": "add[75]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/release-258194/deploy.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "PM re-run at 6c11fc08: test_manual_run_bypasses_quota_cooldown_and_closed_gate (18 passed); auto defers with reason; TTL expiry live §6(в); live manual run not required by OI-2026-11-12 §6"},
    {"req_id": "P0IM-AC-MATRIX-UI", "row_ref": "add[77]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s7accept/matrix-prod.json", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "4 visual checks + 11 screenshots (1536/390, 2.4s scope race, foreign chat_id); residual = Reviewer's own counterexamples and real TMA host (environment limit)"},
    {"req_id": "P0IM-AC-ORDER", "row_ref": "add[80]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/r0/diagnosis-2.58.188.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "read-only fact check (c087253d) before edits, then 2.58.191-194 in order"},
    {"req_id": "P0IM-AC-POLICY", "row_ref": "add[81]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/release-258194/live-overview-2.58.194.json", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "configuration.enabled=true on both chats; no OFF/SHADOW; DDL=0 and no new flags (deploy.md §1)"},
    {"req_id": "P0IM-AC-POSTREL", "row_ref": "add[84]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s7accept/binding-992f45ab.md", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "post-release screenshots of both chats (visual/ac-postrel-*), delivery artifacts 9e6da9ef/1620/11107, prod status; Reviewer verdict becomes the review artifact"},
    {"req_id": "P0IM-S5B-NODISCARD", "row_ref": "add[85]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/evidence/s5b/binding-e92cdcd5.md", "candidate_commit": "e92cdcd5caedb93dee865e9a819ac8b386787b52",
     "basis": "independent Reviewer pass with fake sender in isolated worktree: queued row, byte+sha equality, journal preserved, restart exactly one send, expiry zero sends; live not_delivered reason"},
    {"req_id": "P0IM-S5B-QUOTA", "row_ref": "add[87]", "category": "B", "status_after_review_proposal": "VERIFIED",
     "artifact_path": "plans/features/p0-init-meme-ux-diag/release-258194/live-overview-2.58.194.json", "candidate_commit": "6c11fc08ddade1edf0c4fb274e7f1bf93f852a26",
     "basis": "live spent 3/3, delivered 2, not_delivered 1 publisher_not_bound, screen text; counters not conflated"},

    {"req_id": "P0IM-AC-NODUP", "row_ref": "items[3]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "no independent structural audit of the combined diff"},
    {"req_id": "P0IM-AC-NODUP", "row_ref": "add[4]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "same as items[3]"},
    {"req_id": "P0IM-AC-NODUP", "row_ref": "add[71]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "same as items[3]"},
    {"req_id": "P0IM-AC-SETTINGS", "row_ref": "items[6]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "no before/after snapshot of prompt registry and saved settings"},
    {"req_id": "P0IM-AC-SETTINGS", "row_ref": "add[79]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "same as items[6]"},
    {"req_id": "P0IM-AC-SETTINGS", "row_ref": "add[82]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "same as items[6]"},
    {"req_id": "P0IM-PB-LLM", "row_ref": "items[23]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "f2d3619d implements honest null only; provider/model/slot, prompt versions and actually sent messages are not recorded or shown; architecture/owner decision required"},
    {"req_id": "P0IM-PB-LLM", "row_ref": "add[44]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "same as items[23]"},
    {"req_id": "P0IM-PB-ACCESS", "row_ref": "add[46]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "protected full-text disclosure with RBAC/redaction/retention policy does not exist; coupled with PB-LLM decision"},
    {"req_id": "P0IM-PB-MANUAL", "row_ref": "add[45]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "manual trace lacks marker release and TTL per attempt; no artifact"},
    {"req_id": "P0IM-OV-LIST", "row_ref": "add[31]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "journal row lacks manual/auto label (live capture confirms absence); mode already exists in API"},
    {"req_id": "P0IM-OV-SAMPLE", "row_ref": "add[33]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "sample semantics never compared on the deployed build"},
    {"req_id": "P0IM-OV-SAMPLE", "row_ref": "add[34]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "same as add[33]"},
    {"req_id": "P0IM-OV-SAMPLE", "row_ref": "add[35]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "same as add[33]"},
    {"req_id": "P0IM-OV-SAMPLE", "row_ref": "add[36]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "same as add[33]"},
    {"req_id": "P0IM-OV-SAMPLE", "row_ref": "add[37]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "same as add[33]"},
    {"req_id": "P0IM-PB-FILTERS", "row_ref": "add[40]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "filters/pagination/reason search implemented at 6c11fc08 but never exercised; tests cover 2 of 6 dimensions; 'search' semantics unclear"},
    {"req_id": "P0IM-S6-EFFECTIVE", "row_ref": "add[65]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "4 of 5 gate layers live (image_module missing), heartbeat/providers absent, second chat layers not rendered, no before/after settings snapshot"},
    {"req_id": "P0IM-AC-MATRIX-CONFIG", "row_ref": "add[73]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "two acceptance sub-cases uncovered: probability 100% (test exists: test_probability_one_is_reported_as_no_draw) and 'no occasion at L1' (observer l1_silent / OV-SILENT)"},
    {"req_id": "P0IM-AC-MATRIX-FAIL", "row_ref": "add[74]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "no tests for abort after LLM A/B and for empty image; early gates without job_id, publish conflict, old incomplete rows provable by existing tests"},
    {"req_id": "P0IM-AC-MATRIX-RBAC", "row_ref": "add[76]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "no secret-leak scan of the full trace; competing holders provable by P0IM-ID-CONC"},
    {"req_id": "P0IM-AC-DONE", "row_ref": "add[78]", "category": "C", "status_after_review_proposal": "PENDING",
     "artifact_path": "", "candidate_commit": "", "basis": "aggregate readiness criterion; PM rollup after the rest"}
  ],
  "status_corrections": [
    {"req_id": "P0IM-ID-FINISH", "row_refs": ["items[17]", "add[57]"], "current": "VERIFIED",
     "proposed": "REVIEW until the combined-candidate Reviewer artifact exists",
     "basis": "bound to 16cdb3b8; no independent review artifact anywhere in the repo; claims in slice_progress/residual_windows are prose"},
    {"req_id": "P0IM-ID-CONC", "row_ref": "add[59]", "current": "VERIFIED",
     "proposed": "REVIEW until the combined-candidate Reviewer artifact exists", "basis": "same as P0IM-ID-FINISH"}
  ],
  "voluntary_observations": [
    {"id": "WO-258194-S5B-DEFERRED", "type": "E", "mandatory": false,
     "trigger": "real production attempt reaching publisher_not_bound/publish_blocked with an already-paid image, then delivered by the bound sender",
     "read_fields": ["journal terminal row publication.output.tg_message_id", "meme_last_delivery.status/message_id/run_id", "mca_bot_outputs row with same correlation_id"],
     "note": "does not hold S5b rows or the epic; ordinary post-release observation"}
  ],
  "anomalies": [
    "no durable independent review artifact for any candidate of this epic (16cdb3b8 has none at all)",
    "f2d3619d absent from the map; its claimed P0IM-PB-LLM coverage is factually wrong (honest null only)",
    "recorded_limits S4TRACE-NO-LLM... says code outputs provider/model/prompts/messages - false at 6c11fc08",
    "recorded_limits S3OV-COMPARE-READS-OTHER-CHAT is stale: other-chat mode was exercised at 2.58.194",
    "evidence/s7accept/run/result.json dangling (referenced by matrix meta, exists nowhere)",
    "s7accept visual/** + prod-snapshot only on init/meme-s7-accept (8d2553ed); S3-OV png + s5b playwright only on release line; bindings/r0/s2id only on master",
    "case split evidence/s3ov vs evidence/S3-OV will break paths on Linux",
    "release gate at 6c11fc08: errors=216 (bookkeeping: per-row evidence not re-anchored to the final candidate)"
  ]
}
```

---

## 12. Ограничения этой классификации (что не проверялось)

- Я не запускал production, не менял вероятности, не отправлял сообщения в Telegram, не выполнял `/meme`
  от имени владельца; живой ручной путь не воспроизводился по прямому запрету (`OI-2026-11-12 §6`).
- Не переигрывал e2e-стенд `tests/ui_initiative_rework_e2e.py` и полные серии 15 файлов — использовал
  зафиксированные прогоны `release-258194/deploy.md §3` и точечные прогоны:
  - `6c11fc08`: `test_meme_command_autodelete.py` → **18 passed**; `test_p0_meme_publication_hotfix.py` +
    `test_p0im_s5_meme_marker_interrupt.py` + `test_publication_binding_delivery.py` → **72 passed**;
  - `f2d3619d`: `test_initiative_publications_api.py` + `test_meme_init_diagnostics.py` → **78 passed**;
    `node tests/js/initiative_ui_rework_test.js` → `INITIATIVE-UI-OK`.
  - `requirements_gate.py check --stage release --candidate 6c11fc08 --deployed-commit 6c11fc08` → `errors=216`
    (read-only, ничего не менялось).
  - `git merge-tree --write-tree 16cdb3b8 f2d3619d` → `1dea083f`, конфликтов нет.
- Не проверял физически `evidence/s7accept/run/**` на других машинах/ветках за пределами локального репозитория;
  вывод «не существует» относится к проверенным ссылкам (`HEAD`, `6c11fc08`, `8d2553ed`, `16cdb3b8`, `f2d3619d`).
- Не выносил суждений о качестве UI по существу (это визуальный акт Reviewer) и не пересматривал
  семантику уже VERIFIED строк, кроме двух, где отсутствует ревью-артефакт (§10.1).

Housekeeping: временный каталог анализа `WorkspaceData/runs/.../temp-8410177eac` закрывается после сдачи
(`run-close --confirmed-idle --confirmed-evidence`); в дерево проекта ничего не добавлено, кроме этого файла.
этого файла.
