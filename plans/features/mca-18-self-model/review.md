# review.md — `mca-18-self-model` — Review (T-5092 @Reviewer, 06.10.2026)

## Вердикт: **Needs Fixes**

Блокирующих находок — 3 (H-1/H-2/H-3), все исправимы в одном ограниченном rework-цикле. Механика, DDL, OFF-паритет и гарантии воспроизводимы — Builder-claim'ы подтвердились; блокируют поведенческие дефекты, а не инфраструктура.

## Binding

- **HEAD:** `23cb2a1c9244ed1203c662ef61a90c66d811a134` (master). ⚠️ Примечание: бриф dispatch называл HEAD `92252d1` — репозиторий ушёл вперёд (4f960cb/44c6fd7/23cb2a1); биндинг взят на фактическом HEAD, на котором работали код/тесты.
- **Кандидат:** незакоммиченный working tree (две Builder-сессии, ничего не staged/committed).
- **Манифест:** `plans/reports/mca18_wth_manifest_review.txt` — MANIFEST_SHA256 `5b20843c5e52da4fb40727860a55ebef3197e6c10fff0d87af64ec91d44b84ea`, FILE_COUNT 35 (изменённые M-файлы + новые фичевые файлы; recipe — sha256 по отсортированным строкам «hash  path»).
- **Исключения из recipe:** `plans/workflow_state.md` (process-журнал), `plans/docs/mca-round1027-arch-frames.md` (чужой WIP), untracked-debris (`.playwright-mcp/`, `node_modules/`, `package.json`, `package-lock.json`, `tools/_ui_asap43_*`, `plans/verification_cache.json`); сам манифест — самореференция.
- `plans/current_task.md` — не тронут (проверено `git diff`).

## Находки

| # | Severity | Файл:строка | Суть / evidence | Blocking |
|---|---|---|---|---|
| H-1 | **High** | `services/mca_self_model.py:1645/:1670` + вызов `services/bot_persona.py:266–272` | В `render_frame_block` контроль `if not is_aware_ai:` проверяет ПАРАМЕТР (вызывается с None → `not None`=True), а не вычисленный `aware` (переменная мертва). Точка сборки вызывает `render_frame_block(frame, name=…, biography=…, overrides=…)` БЕЗ `is_aware_ai` → `SELF_MODEL_FALSE_BLOCK` дописывается **Всегда**, в т.ч. при `is_aware_ai=True`. Репро: для aware=True, param=None → FALSE_BLOCK в блоке (воспроизведено). Тихая инверсия настройки в единственной точке сборки — нарушение §28.2 `:1522`/`:1525` («не инвертировать молча»), противоречивые инструкции aware-персонажу. Тесты не ловят: `test_contract_empty_persona…` проверяет только наличие aware-строки; `test_render_frame_block_a58…` передаёт параметр явно. | **да** |
| H-2 | **High** | `services/dream_worker.py:2506–2512`; `services/mca_self_model.py:1751–1755` (legacy), `:1197–1202` (promote) | Прод-пайплайн инертен: единственный прод-поставщик наблюдений (dream-хук) и legacy-разбор пишут `dimension=None` → promote всегда завершается `candidate_unmapped_dimension`, активное правило не создаётся; `reinforce_rule` прод-вызовов не имеет (проверено grep). Следствие: `mca_behavior_rules` не получает active-строк, `snapshot.traits` всегда пуст, динамическая цепочка R4→R5 (`:1556`, `:1568` «фоновые LLM преобразуют наблюдения в кандидатов») и live-поведение A60/A61 + §28 преамбула `:1488–1490` недостижимы; T-5095 заведомо не пройдёт. Тесты проходят, создавая правила вручную (`dimension="резкость"`). Builder это недоскопировал. | **да** |
| H-3 | **High** | `tools/mca18_paired_replay.py:187–226` | Параметр `generations` мёртв: цикл генерирует 1 пару на ход; реальный прогон даст не «≥3 генерации на условие» (§28.7), а n=1 → разброс = межсценарная вариация, не стохастичность LLM; риск ложного `rule_verified`. Эмпирика: `run_replay(fake, generations=3)` → llm_calls=68 (ожидание 30·3·2+30=210). Тесты масштаб по generations не проверяют. Целостность харнесса для A63-измерения не обеспечена. | **да** |
| M-1 | Medium | `web/api/routes.py` (GET /persona/rules/{id}/sources) | Эндпоинт игнорирует `rule_id` и `mca_behavior_rules.source_observation_ids` — возвращает последние 200 наблюдений всем правилам → цепочка «черта → основания» (§28.6 `:1586`) вводит владельца в заблуждение. R17 формально ок (preview_len). | нет |
| M-2 | Medium | `services/mca_gates.py:1286–1291` + `config/settings.py` (Δ) | `MCA_MOOD_TTL_HOURS` санкционирован (spec §8.5), но ClassVar в settings.py не добавлен → `getattr(settings, name, 6)` всегда 6; env=2 проигнорирован (эмпирически: 21600). Плюс `mood_ttl_seconds()` не вызывается прод-кодом: никто не вычисляет `valid_to` из TTL (mood-писатель отсутствует). | нет |
| L-1 | Low | `services/mca_self_model.py:450–462` | `identity_binding='runtime'` ставится и при совпадении, и при расхождении bot_user_id — расхождение привязки НЕ видно в snapshot/UI (против утверждения evidence «расхождение видно в identity_binding»). | нет |
| L-2 | Low | `services/database.py` (`_migrate_self_model_v31`, индексный self-guard) | `cols` определён только внутри `if _table_exists("graph_facts")` — отсутствие graph_facts при v31-миграции даёт NameError (теоретически; миграция под backup-guard). | нет |
| L-3 | Low | `services/mca_self_model.py:1237–1243` | Docstring `_upsert_rule_candidate` обещает «ДОБАВЛЯЕТСЯ в source_observation_ids» — UPDATE их не дополнит. Поведение безопасно (подкрепления нет), но контракт описан неверно. | нет |
| L-4 | Low | `web/index.html` / `app.js` (карта в «Личность») | Placement-дрейф §28.6: пауза/источники/компакт размещены в экране «Личность», а не в «Память»/«Аналитика» (без нового раздела/маршрута — CA-18-8 соблюдён). Судить — live-приёмка T-5095. | нет |
| L-5 | Low | `services/bot_persona.py:447–449` | K1 ON + `lore_runtime.get_lore_db() is None` → тихий уход в legacy без события (задокументированный elsewhere fail-open; здесь события нет). | нет |

Pre-existing (не связано с mca-18, зафиксировано для backlog): предупреждение «closed 7 leaked aiosqlite connections» (старые тесты mca-05/10b); ослабление frontier-гардов `== 30` → `>= 30` в `test_mca05…` (конвенция волн mca-10b, осознанная).

## Ответы по §28.1–§28.7

- **§28.1 (R1):** разрывы закрыты: F-3 `get_traits` fail-open → warning+событие (тест `test_get_traits_failure_event_not_silent`); пустая персона → различимый минимум (A58-минимум, тесты); три состояния ошибки. Тихий уход при `db is None` — L-5.
- **§28.2 (R2):** snapshot-поля присутствуют; persona_version = хеш содержимого (модель/токен не входит — тест); rebind явный (admin-метод, agent_id стабилен — тест); capabilities из реестра (`can_analyze_images=False` до mca-19, «помню всё»=False); **три настройки разведены, но H-1 инвертирует is_aware_ai в промпте при ON**.
- **§28.3 (R3):** v31 = 4 таблицы + 9 nullable-колонок `graph_facts` (CHECK-enum, revision DEFAULT 1, REUSE status/supersedes/weight/provenance v17) — санкция соблюдена; атрибуция: self по agent_id, «я» в цитате → автор цитаты, «бот» без референта → ambiguous (self_trait → None), роли не сливаются — негативные тесты есть; 8 запретов таблицы enforced guard-функциями до записи + тест на каждый; adoption требует basis_refs (UNIQUE; повтор фразы группой ≠ позиция); позиции только из opinion+adoption.
- **§28.4 (R4):** стадии/авто-валидация/lifecycle в коде; 8 dimensions; новое имя → candidate; precedence `scoped_request > derived_traits` (разовая просьба затеняет, не удаляет); анти-самоусиление: dedup по исходным событиям, own-output-under-trait через mca-22 ledger, гарды ≤0.1/≤0.2, ослабление без капа — **механика есть, но прод-путь инертен (H-2)**.
- **§28.5 (R5):** frame в decision (frame_version аддитивно, enum цел)/direct/autonomous (тот же поток)/synthesis+verbalizer (`character_block`) — через швы mca-08, второй контур отсутствует; techn-вызовы без стиля; form_contract не тронут (`final_check` честно не инструментирован); один snapshot на запуск (ContextVar holder); fallback LKG-TTL/minimal честный (события никогда не outcome=success при деградации).
- **§28.6 (R6):** legacy-разбор идемпотентен по `legacy_ref`, fail-closed на ошибке lookup; source_refs = `legacy_trait:{pg_id}` без фабрикации; непроверенное — `legacy_unverified`; manual → самопроверка (но остаётся неприведённым кандидатом — часть H-2); FIFO сохраняет raw; chat→global не выполняется. UI: карта в существующем экране, без новых разделов; три статуса различимы (applied_now/rejected_now/версии). M-1 — источники не фильтруются.
- **§28.7 (R7):** контрактные тесты 100% зелёные (7/7 в 86); paired replay: харнесс честен по рубрике/слепоте/no-send, **но параметр ≥3 генераций не подключён (H-3)** — реальное измерение запрещено запускать до фикса; `rule_verified` до прогона не заявляется (no-false-acceptance соблюдён).

## Что я запускал (точные счётчики)

- mca-18 focused (6 файлов): **86 passed**. Контрактные (7) + replay-контур (6) — зелёные.
- Смежный слайс (19 файлов: bot_persona, mca-08×2, mca-09 off-parity+block A, mca-16×2, dream×2, mca-10b×2, mca-14, database, f8_registry, param_catalog, settings_persistence, mca-17a, mca-01, mca-05): **632 passed**.
- Полный suite (санкция T-5091) — мой собственный прогон: **12072 passed / 7 failed / 1 skipped, 7:19** — совпадает с числами Builder T-5091 (12072 passed / 7 failed; his clean-HEAD stash-run: Δ новых падений = 0); те же 7 красных pre-existing + мои spot-верификации без stash: красные #2–4 — stale-пины «2.58.57» при `APP_VERSION=2.58.61` (settings.py:3106, mca-18 версию не трогает); красный #7 `test_registry_process_intent_initiative` — зелёный standalone (order-зависимость, не от mca-18).
- Собственные репро: K1 OFF byte-parity legacy-блока (вкл. `_NO_AI_DISCLOSURE_BLOCK`) — совпадение; H-1 FALSE_BLOCK при aware=True/param=None; H-3 llm_calls=68 при generations=3; env `MCA_MOOD_TTL_HOURS=2` игнорируется (21600).
- Реестры: REASON_CODES=257 (один словарь), KILL_SWITCHES=76 (ровно +3), `self.model` v1/8 стадий; guard-бампы (routes-pin L-F11S-1, single-writer 176→182, f8_baseline) сверены.

## Security walk (T-1…T-10, вместо Scanner T-5093 рамкой)

T-1 (инъекция черт): ambiguous→self_trait=None; self_trait требует proven self + applicability; шаги капнуты — код+негатив-тесты ✓. T-2: legacy без субъекта → candidate; manual — действия владельца ✓. T-3: dedup по событиям + own-output-not-independent + капы (прод-вызовы отсутствуют — тихо, инертно, безопасно) ✓. T-4: persona_version content-hash; rebind явный ✓ (дивергенция не видна — L-1). T-5: роли различны, ambiguous не меняет характер; capabilities ≠ биография ✓. T-6: opinion ≠ factual constraint (отдельный слот); payload/JSON без стиля ✓. T-7: честный stale/minimal fallback, никогда не success ✓. T-8: ошибки чтения — события ✓. T-9 (R17): события — ID/коды/числа; sources — length-only; raw-тексты не системные инструкции (правила из фиксированного канона) ✓. T-10: OFF = бит-в-бит 2.58.61 (моё репро + тесты) ✓. Critical/High по безопасности — 0 (H-1…H-3 — корректность/честность, не security).

## Disposition replay-измерения (п.5 мандата)

Реальный прогон 30×≥3 — **live-class item после деплоя** (требует LLM-бюджета и санкции; no-false-acceptance: `rule_verified` до прогона не заявляется). Оставлять PENDING, НО запускать только после H-3-фикса — текущий харнесс не может исполнить замороженную методику (≥3 генерации) и способен выдать ложный directed_effect. Не блокирует деплой сам по себе, блокирует *измерение*: в rework H-3 обязательно + тест-скалирование вызовов.

## Bounded rework (ОДИН цикл, ~3 кода + тесты; без других зон)

1. **H-1:** `services/mca_self_model.py` `render_frame_block` — финальную проверку заменить `is_aware_ai` → вычисленный `aware` (строка `:1670`); либо точка сборки (`bot_persona.py:267–271`) обязана передавать effective-aware. Acceptance: контракт-тест, что через `build_persona_prompt_block` с holder-кадром при `is_aware_ai=True` `SELF_MODEL_FALSE_BLOCK` ОТСУТСТВУЕТ (сейчас RED), при False — присутствует и `_NO_AI_DISCLOSURE_BLOCK` не вернулся.
2. **H-2:** либо (a) подключить отображение наблюдений в закрытый набор 8 dimensions в dream-хуке (расширить `PERSONA_EVOLUTION_PROMPT`/`parse_persona_traits` до пар «text, dimension∈8» с fallback NULL→candidate с причиной; `dream_worker.py:2506`, `dream_prompts.py:291–348`), либо (b) документированная санкция, что активация в этой волне остаётся только владелец-API/владельцем — в обоих случаях добавить сквозной тест «наблюдение сна → активное правило → кадр содержит инструкцию → ответ под чертой помечен ledge-тегом» (A60/A61 live-path) и честно скорректировать evidence/spec-статусы. Без санкции вариант (a) обязателен — это требование `:1568`.
3. **H-3:** `tools/mca18_paired_replay.py:204–213` — встроить `generations` в цикл генераций пары + тест «llm_calls масштабируется ×generations; разброс считается по повторам».
4. Попутно (в тот же цикл, дешёвые): M-1 (фильтр sources по `source_observation_ids` правила), M-2 (ClassVar `MCA_MOOD_TTL_HOURS` в settings.py).

## Residual notes

- Live T-5095 — **[PENDING OWNER]**, реальный чат, post-deploy (не имитировать).
- Полная матрица/фуннель/виджет-рендер — mca-17c (widget-ID — контракт); N-1 mca-10b селектор не подключён (گزpec §0/ADR D9 — соблюдено).
- После rework: пересмотр ТОЛЬКО затронутых зон (точка сборки/контракт-тест FALSE-block; dream-хук/lifecycle-тесты; харнесс), полного перезапуска не требуется, если дифф не выйдет за рамки.

R17: секретов/сырого контекста в отчёте нет.

---

# Итерация 2 (rework-перепроверка, T-5092, 06.10.2026)

## Вердикт: **Approved**

Блокирующих находок нет. H-1/H-2/H-3 закрыты в коде, подтверждены независимой инспекцией, собственными репро и целевыми прогонами; RED-доказательства Builder'а согласуются с реальными тестами (не fabricated); соседние ветки не повреждены. M-1/M-2 закрыты попутно, disposition итер. 1 по M-2 сохранён без изменений.

## Binding

- **HEAD:** `23cb2a1c9244ed1203c662ef61a90c66d811a134` (не изменился с итер. 1).
- **Кандидат:** незакоммиченный working tree (rework поверх кандидата итер. 1; ничего не staged/committed).
- **Манифест:** `plans/reports/mca18_wth_manifest_review.txt` — MANIFEST_SHA256 `d7d0071f9aeeab30e0368b397da0fe637d3ce3eb053b49ebc42a0dba48bb8c59`, FILE_COUNT **37** (см. Incidental I-1: +2 файла к 35 итер. 1). `review.md` — отчёт Reviewer'а, вне recipe (как и в итер. 1).
- Контрольные совпадения хешей: `services/mca_self_model.py` = `49e4125d…b9a5d1c` (равен SHA256, заявленному Builder'ом после RED-отката/восстановления); `web/api/routes.py` = `72c22193…c461` (равен бампнутым пинам `ROUTES_SHA256_F11` в f8_registry и block_d); `services/bot_persona.py` не менялся с итер. 1 (фикс H-1 целиком в `render_frame_block`).

## Перепроверка блокеров

**H-1 — закрыт.** Код: `aware = frame.is_aware_ai if is_aware_ai is None else bool(is_aware_ai)` (`mca_self_model.py:1704`), финальная проверка `if not aware:` (`:1733`) — по вычисленному значению; кадр несёт effective из snapshot (`:1644–1645`: `effective(True) and not is_error`); единственный прод-вызов — точка сборки `bot_persona.py:275` без параметра (настройка проходит честно). Независимое репро (4 комбинации): aware-кадр без override → FALSE_BLOCK отсутствует; override=False → присутствует; не-aware кадр → присутствует; override=True → снят. Контракт-тесты `test_contract_false_block_uses_effective_awareness` (ассерты 1-в-1 против старого бага: со старым `if not is_aware_ai:` упал бы) и `test_contract_empty_persona_true_false_assembly` (сквозной, через holder-кадр `resolve_character_context` → `build_persona_prompt_block`) — настоящие RED-тесты.

**H-2 — закрыт.** Dream-хук `dream_worker.py:2501–2537`: `parse_persona_measurements` → пары «text, dimension» (null/незнакомое имя → NULL на записи `record_trait_observation:1146–1149` — валидация по `INITIAL_DIMENSIONS`/`FOREIGN_DIMENSIONS`) → `promote_observation`: NULL → честный отказ `candidate_unmapped_dimension` (`:1243–1248`), foreign → experience, subject≠self/source-missing → отказы, chat-правило создаётся с applicability. Legacy-parse `:1821`: `dimension=infer_dimension(text)`; manual + приведённый → promote (может стать active), остальной → `legacy_unverified` кандидат. `reinforce_rule` (`:1444–1509`) с гардами дедупа по событиям, независимости источников (own-output-under-trait через mca-22 ledger) и капами ≤0.1/≤0.2. Дрейф промпта исключён конструктивно: `PERSONA_TRAIT_DIMENSIONS` строит `PERSONA_EVOLUTION_PROMPT`, зеркальность `INITIAL_DIMENSIONS` закреплена тестом. Сквозные тесты настоящие: сон → active-правило (dimension «краткость») → инструкция в кадре → rule-tag в ledger; dimension=null → без роста правил; A61: свой ответ под чертой не подкрепляет, независимое → version+1/target 0.1, тот же refs-набор → дедуп.

**H-3 — закрыт.** `tools/mca18_paired_replay.py:213`: `for _gen in range(generations)` — параметр живой, индекс генерации пишется в score, `evaluate` получает generations. Независимый dry-run (offline, фейк-LLM): generations=1 → paired=68/calls=102; generations=3 → paired=204/calls=238 — масштаб ровно ×3; на константном фейке `rule_verified=False` (оценщик честен). Scaling-тест `test_run_replay_generations_scale_and_spread` присутствует; числа совпадают с evidence Builder'а (204/238).

**M-2 — не регрессировал, зафиксирован.** `MCA_MOOD_TTL_HOURS: ClassVar[int]` добавлен в `config/settings.py:1550` (env-парсинг `_env_int_min`); живое репро: env=2 → settings=2 → `mood_ttl_seconds()=7200` (до фикса — 21600). Disposition итер. 1 сохранён: env уважается, но `mood_ttl_seconds()` по-прежнему не вызывается прод-кодом (mood-писатель с `valid_to` отсутствует) — non-blocking, backlog.

**M-1 — закрыт.** `web/api/routes.py:2388–2408`: источники правила = разбор `source_observation_ids` ЭТОГО правила (кап 200), а не последние 200 наблюдений всем; пусто → честный пустой ответ. Тест `test_ui_rule_sources_filtered_by_rule` присутствует. Бамп гвардов под изменённый routes подтверждён фактическим хешем файла.

## Что я запускал (итерация 2)

- Focused mca-18 (6 файлов): **93 passed** — воспроизведено моим прогоном (сходится с Builder и повтором Оркестратора после прерывания).
- Смежные слайсы (мои прогоны): bot_persona + mca-08×2 + dream×3 — **219 passed**; mca-16×6 + mca-14 — **108 passed**; direct_chat×4 — **222 passed**.
- Независимые репро: H-1 (4 комбинации render), H-3 (scaling ×3 + честность оценщика), M-2 (env=2 → 7200).
- Хеши: routes.py vs бампнутые пины; mca_self_model.py vs SHA256 из evidence; сверка набора файлов git-status с манифестом.

## RED-согласованность (проверка на fabrication)

Каждый названный в evidence RED-тест статически противоречит старому поведению: H-1 — тест ассертит отсутствие FALSE_BLOCK при aware=True без override (старый код дописывал всегда); H-2 — сквозные тесты требуют active-правило/тег (при dimension=None promote возвращает `candidate_unmapped_dimension`, правило не создаётся); H-3 — тест ассертит paired_generations == n×3 (при `range(1)` арифметически ложен). Протокол отката/восстановления с SHA256-сверкой согласуется: хеш `mca_self_model.py` в манифесте совпал с заявленным.

## Incidental (итерация 2)

- **I-1** (related, закрыт здесь): манифест итерации 1 покрывал 35 файлов и пропускал `services/dream_prompts.py` и `tests/test_dream_persona_traits.py` — оба изменены, и именно туда лёг H-2-rework. В манифесте итерации 2 покрытие полное (37). На вердикт итер. 1 не влияло (обе зоны были инспектированы напрямую).
- **I-2** (uncertain/pre-existing flake, non-blocking): единичный недетерминированный падёж `test_dream_worker.py::TestDistillation::test_cluster_distilled_to_belief` (aiosqlite «no active connection») в одном прогоне 6-файлового слайса; standalone, в паре и в повторе группы — зелёный (219 passed). В полных прогонах (12082/7) отсутствует; путь дистилляции не пересекается с mca-18. Кандидат в backlog.
- **I-3** (related-nonblocking, от Builder): CLI-запуск `tools/mca18_paired_replay.py --dry-run` из docstring требует `PYTHONPATH=.` и `PYTHONIOENCODING=utf-8`; контур тестов не зависит. Backlog.

## Disposition (без изменений по существу)

- Реальный paired-replay прогон 30×≥3 — live-class item post-deploy (LLM-бюджет + санкция владельца); харнесс теперь методически способен его исполнить (≥3 генераций). `rule_verified` до прогона не заявляется.
- L-1…L-5 — без изменений (соответствующие файлы не менялись rework'ом); полный suite не перезапускался мной — reused evidence T-5091/T-5096 (12082 passed / 7 pre-existing / 1 skipped, Δ=0) + мой focused-прогон + смежные слайсы; blast radius rework покрыт.
- T-5095 (live-приёмка) — PENDING OWNER, post-deploy; bump APP_VERSION 2.58.62 — на шаге деплоя (T-5094).

**Join-barrier:** T-5093 (Scanner-аудит) — разблокирован.

R17: секретов/сырого контекста в отчёте нет.
