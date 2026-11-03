# RC-DIRECT-SELFCORR — возражение и пересмотр собственного ответа в Direct

- Кандидат: ветка `rc/selfcorr`, база `33b08401` (ветка `evol/impl`).
- Worktree: `WorkspaceData\worktrees\c742e4de9e92c489\rc-selfcorr-735bcb6d79df-21825fcb`.
- Контракт: `plans/features/evol/arch/reply-context-integrity-v5-contract.md` §3–§5;
  источник владельца `plans/owner_inputs/2026-11-03-evol-reply-context-integrity-v5.md`
  §12.1–§12.4 + §13 сц.71–96 (`DIRECT-SELF-CORRECTION-01`).
- Шов: существующий Direct pipeline — `direct_chat_service` (L1 → L2 Writer),
  `canonical_context`/`thread_chain` (речевая проекция), история собственных
  ответов (`mca_bot_outputs`), `prompt_composer` (манифест), `mca_events`
  (существующая диагностика). Новых таблиц, объектов, агентов, dataclass'ов,
  баллов уверенности, LLM-judge, регенераций, regex-чистки текста и бюджетов нет.

## 1. Что теперь верно по §12 (клауза → реализация)

| §12 | Реализация |
| --- | --- |
| п.1 референт возражения | `direct_chat_service._build_correction_frame()` (`:11974`): лестница оснований — подтверждённый Telegram Reply (`reply_to_message.from_user.id == bot_id`), выделенная цитата (`message.quote.text`), затем смысловая привязка к последней доставленной собственной реплике (`_correction_last_own_outputs`, `:2865`, источник — ledger `mca_bot_outputs`, bounded LIMIT 4). Нет подтверждённой связи → рамки НЕТ (не «первый попавшийся предмет»). Несколько равноподходящих своих реплик + другие сообщения между ними → `link="ambiguous"` + «уточни, а не выбирай наугад» + метки альтернатив. **Уровень уверенности назван атрибутом `challenge`**: `claimed` только при подтверждённом Reply, `unknown` для семантической/неоднозначной/нераспознанной ветки — там рамка прямо говорит, что факт возражения НЕ установлен (см. §10). |
| п.2 уровни утверждений | Роли печатаются отдельными строками `_render_correction_frame` (`:3030`): «твоё прежнее утверждение (роль: твои слова…)», «возражение (роль: текущая реплика человека)», «выделенный фрагмент», «первоисточник». Своё утверждение НЕ получает статуса доказательства: «это утверждение, а не доказательство собственной правоты». В ветке `challenge="unknown"` та же роль названа «твой последний доставленный ответ (роль: твои слова; является ли он предметом несогласия, по данным НЕ установлено)». |
| п.3 единица счёта | `_correction_counting` (`:2956`) + `_correction_reference_kind` (`:2916`): раздельно считаются самостоятельные реплики (и вопросительные предложения в них), ссылки/цитаты на свои прежние реплики, цитаты/ссылки на СЛОВА БОТА (`refs_bot`, не «другой участник»), ответы другим, ссылки вне окна; строка «единицы не смешиваются» + подпись единицы. Подмена «вопросы ↔ сообщения» невозможна молча (см. мутацию M2). |
| п.4 перепроверка своего вывода | Канон Writer'а `chat_prompts._VERBALIZER_SELF_CORRECTION_RCA1` (`:663`): прежний ответ перепроверяется по истории; обоснованное возражение → признать конкретную ошибку и исправить вывод в этом же ответе; ошибочное → возражать аргументированно, без автоматического извинения; нехватка данных → честно сказать, чего не видно, и не объявлять победителя. Рамка даёт факты покрытия окна («реплик человека в окне: N»). |
| п.5 прагматика | Тот же канон: насмешка/сарказм/резкое замечание о ответе — возможная обратная связь о поведении, не буквальная тема и не новый вопрос; прямой вопрос по существу (объяснить понятие/критерий/проверить расчёт) отвечается буквально. Списка триггерных фраз нет; слов инцидентного диалога в промпте нет. |
| п.6 ход разговора | Смысловая привязка считается по хронологии окна и ledger-времени (`sent_at`), а не по «соседнему сообщению»: `intervening` — число реплик человека между своей репликой и возражением (печатается в рамке). |
| п.7 личность | Канон: «Признание ошибки не требует стерильного тона», «несогласие не требует унижать человека», «победа в споре не является критерием качества ответа»; Core/Expression/Humor/Style-слои не тронуты. |
| п.8 без долговременной истины | Локальная коррекция живёт только в этом ответе: новых хранилищ/«базы опровержений» нет; Experience-эпик не затронут. |
| п.9 роли и адресность | Reply на реплику участника → `subject="participant"` («слова человека, не твои»); канон: отвечать за свои слова, чужие не присваивать и не извиняться за них от своего имени. |
| п.10 без ложного знания алгоритма | Канон: о собственном устройстве не заявлять без достоверных данных, свой прежний вывод — «моя интерпретация», реально полученные данные о системе можно называть точно. |

## 2. Форма промпта (фактический payload, 4 роли)

Система (канон Writer'а, `direct.base.l2_writer` = `l2-writer-self-correction-rca1`,
sha12 `44736968bc76`): добавлена секция «ВОЗРАЖЕНИЕ И СВОЙ ПРЕДЫДУЩИЙ ОТВЕТ»
(прежние байты заморожены в `PREV_CHAT_VERBALIZER_EVR1`, ступень миграции и
откат — в `prompt_migrations`).

User-часть — новый P0-слот `correction` (`CANONICAL_ORDER` = 15, перед
`current`; `BLOCK_PRIORITY` = P0), образец реального payload:

```
<Correction_Frame link="telegram_reply" subject="own_claim" challenge="claimed" own_in_payload="0" source_present="1" semantic="0" window="3" refs_same="2" refs_bot="0" standalone="1" questions="1">
твоё прежнее утверждение (роль: твои слова, которые оспаривают): M5 — «ты спрашивал это три раза»; это утверждение, а не доказательство собственной правоты
возражение (роль: текущая реплика человека): M4 — Никита (U1)
связь возражения с предметом: Telegram Reply (подтверждено транспортом)
первоисточник: доступен в видимом окне; реплик человека в окне: 3
счёт по видимым репликам человека (единицы не смешиваются): самостоятельных реплик 1, в них вопросительных предложений 1; ссылок/цитат на свои прежние реплики 2; ссылок/цитат на твои прежние реплики (твои слова, не другого участника) 0; ответов другим участникам 0; ссылок вне окна 0
- M1: самостоятельная реплика (вопросительных предложений: 1)
- M2: ссылка/цитата на свою же прежнюю реплику
- M3: ссылка/цитата на свою же прежнюю реплику
</Correction_Frame>
```

- Если своя реплика уже показана в цепочке этого хода — текст НЕ дублируется
  (`own_in_payload="1"`), роль адресуется меткой прогона.
- `link="semantic"` печатает «смысловая привязка по времени и структуре (НЕ
  Telegram Reply)»; `link="ambiguous"` — «несколько твоих реплик одинаково
  подходят … уточни, а не выбирай наугад».
- В этих двух ветках `challenge="unknown"`: возражение не заявлено, роль
  названа «твой последний доставленный ответ», добавлена строка «статус связи:
  не установлено, выражает ли текущая реплика несогласие…» (см. §10).
- Служебных `tg:/msg:/fact:` и голых uid в рамке нет — только метки прогона с
  обратной картой (`SpeechProjection`).

## 3. Наблюдаемость (§12.4) — существующие каналы

- `mca_events` `direct_self_correction` (сборка рамки, `stage="context"`):
  `message_id` = реальный id текущей реплики, `reason_code` ∈
  {`quote_resolved`, `quote_ambiguous`, `quote_unresolved`},
  `usage_json` = `link`, `subject`, `challenge`, `own_in_payload`,
  `source_present`, `semantic`, `window`, `refs_same`, `refs_bot`,
  `standalone`, `questions`.
- `mca_events` `direct_self_correction_delivery` (после генерации):
  `stage` = `l2_writer` | `l2_writer_fallback`, `reason_code` =
  `writer_generated` | `fallback_engaged`, `usage_json.context_representation`,
  `.composer` — какой ход ФАКТИЧЕСКИ дал итоговый ответ.
- `PromptManifest.self_correction` + `manifest_for_events()["self_correction"]` —
  защищённый prompt-manifest прогона (только коды/счётчики, без текстов).
- Статус **не** объявляет «self-corrected»: проверяемого основания для такой
  самооценки нет (§12.4 запрещает хранить непроверенные самомнения LLM как
  факт). «Источники поддерживают/опровергают» кодируются как фактические
  отношения (наличие первоисточника, состав счёта, метки), а не как вердикт:
  детерминированно вывести «поддерживает/опровергает» нельзя, а выдумывать —
  запрещено; материал для вывода модель получает в рамке.

## 4. Тесты

`tests/test_rc_direct_self_correction.py` — 27 тестов (CONTRACT). Проверяют
фактический payload (`_build_user_content` и полный `handle()` → реальные
`messages` L2-вызова), произвольные имена/темы/ID (анти-хардкод §13.92):

| Сценарии §13 | Тест |
| --- | --- |
| 71 | `test_one_question_and_two_quotes_is_one_not_three` |
| 72 | `test_three_real_questions_are_three` |
| 73 | `test_two_questions_in_one_message_are_not_two_messages` |
| 74/75 | `test_reply_to_own_answer_names_it_as_own_claim`, `test_own_previous_answer_is_not_evidence` |
| 76 | `test_canon_allows_justified_disagreement_and_honest_uncertainty` |
| 77 | `test_reply_without_recoverable_text_is_honest`, `test_window_coverage_is_stated` |
| 78/79 | `test_canon_reads_indirect_critique_and_keeps_literal_questions` |
| 80/4/10 | `test_two_equally_plausible_claims_ask_instead_of_guessing` |
| 82/94 | `test_semantic_link_is_marked_as_not_reply`, `test_plain_new_question_without_reply_does_not_claim_challenge` |
| 84/85 | `test_reply_to_participant_is_not_own_claim`, `test_no_structural_link_no_frame` |
| 86/87 | `test_canon_forbids_invented_algorithm_knowledge` |
| 91 | `test_canon_keeps_persona_and_ownership` |
| 92 | все тесты на случайных данных; в каноне нет слов инцидента |
| 93 | `test_flag_off_keeps_previous_payload`, `test_correction_is_p0_slot_before_current`, `test_frame_survives_tight_budget` |
| 95 | `test_l2_payload_has_four_roles_and_canon` (реальный `handle()`) |
| 96 | `test_no_new_llm_call_or_regeneration`, `test_manifest_and_event_carry_codes_not_texts` |
| п.3 роли | `test_quote_of_bot_words_is_not_answer_to_participant` |

## 5. Мутации (правка приложения → профильные тесты краснеют)

Скрипт: `WorkspaceData/runs/.../mutation_run.py` (бэкап+восстановление файла,
без git-операций). База 25 passed; после каждой мутации набор краснеет и
восстанавливается зелёным.

| Мутация | Что ломаем | Поймано |
| --- | --- | --- |
| M1 | своя прошлая реплика подана как основание, а не утверждение | 1 тест |
| M1b | канон снял «прежний ответ ≠ доказательство» | 1 тест |
| M2 | число сообщений молча выдаётся за число вопросов | 1 тест |
| M3 | метафора/насмешка снова трактуется как буквальный вопрос | 1 тест |
| M4 | смысловая привязка выдаётся за Telegram Reply | 2 теста |
| M5 | чужие слова присваиваются боту (`subject=own_claim`) | 1 тест |
| M6 | рамка теряет P0 (вытесняется бюджетом) | 2 теста |
| M7 (ревью) | семантическая ветка снова заявляет возражение (`challenge="claimed"` всегда) | `test_plain_new_question_without_reply_does_not_claim_challenge` |
| M8 (ревью) | цитата слов бота снова считается «ответом другому участнику» | `test_quote_of_bot_words_is_not_answer_to_participant` |

9/9 убиты (M7/M8 — после исправлений §10).

## 6. Прогоны и классификация падений

- `tests/test_rc_direct_self_correction.py` — **27 passed**.
- Direct/контекст/проекция: `test_direct_chat`, `test_direct_context_composer_asap3`,
  `test_evol_reply_context_consumers`, `test_evol_reply_context_integrity_seam` +
  мой файл — **337 passed**.
- Composer/манифест/версионирование: `test_soul1_composer_layers`,
  `test_soul1_composer_parity_off`, `test_soul1_core_composer_integration`,
  `test_soul1_direct_prompt_reads`, `test_evol018_prompt_audit`,
  `test_prompt_migrations`, `test_prompt_versioning_enforcement`,
  `test_direct_chat_prompts`, `test_prompt_baseline`,
  `test_evol016_prompt_activation` — **все зелёные**.
- Широкий прогон `-k "direct or context or composer or target_marking or speech"`:
  кандидат **17 failed / 1992 passed / 1 skipped**, база `33b08401`
  **17 failed / 1965 passed** — те же 17 падений (pre-existing):
  `test_budget_global_toggle_round1024` (3),
  `test_direct_fallback_recompose_asap32` (5), `test_history_w4_fixes` (6),
  `test_native_reply_media_context_round1024` (3). Причина одна и та же на базе:
  тестовые двойники переопределяют `_render_thread`/`_build_user_content` без
  параметра `projection` (TypeError) — регрессий слайса нет. Разница passed
  ровно +27 (два теста §10 + 25 прежних).
- `requirements_gate.py check --stage plan` — `inventory=312 manual=43 scoped=0 errors=0`.

## 7. Осознанно обновлённые пины (без них — ложный зелёный)

1. `tests/test_asap_speech_r3b_canon.py` — байт-эталон канона L2 и лестница
   откатa (добавлена секция; прежние байты = `PREV_CHAT_VERBALIZER_EVR1`).
2. `tests/test_prompt_migrations.py` — ступень миграции/откат L2, sha12 активного
   канона (`44736968bc76`), fingerprint набора (`e9dc109330a8`).
3. `tests/test_history_isolation.py` — слоты `CANONICAL_ORDER` (новый P0-слот
   `correction` перед `current`; относительный порядок прежних kind'ов сохранён).
4. `services/prompt_registry.py` — метка `l2-writer-self-correction-rca1`, печать,
   `FACTORY_SET_SHA256_12` (контракт EVOL-016/018, обязателен).

## 8. Записи вне declared write_scope слайса (обоснование)

`slice-graph.json` для RC-DIRECT-SELFCORR перечисляет
`services/direct_chat_service.py`, `services/prompt_composer.py`,
`tests/test_rc_direct_self_correction.py`. Дополнительно затронуты:

- `services/chat_prompts.py`, `services/prompt_registry.py`,
  `services/prompt_migrations.py` — **обязательный** контракт версионирования
  промптов (AGENTS.md, EVOL-016/018): новая постоянная инструкция Writer'а не
  может существовать вне реестра, метки и печати;
- `services/direct_context_composer.py` — реестр слотов композера
  (`BLOCK_PRIORITY`/`CANONICAL_ORDER`): неизвестный kind получает P2 и
  вытесняется, т.е. без регистрации рамка не была бы P0.

Ни один из этих файлов не входит в write_scope других срезов карты RC (проверено
по `slice-graph.json`); `services/factcheck*`, `handlers/factcheck.py`,
`services/prompt_release_policy.py`, `web/**` не тронуты.

## 9. Что осталось за пределами слайса

1. **S6 (приёмка/трасса):** привязка 41 строки `RC-DIRECT-SELFCORR`
   (L00335–L00344, L00350–L00354, L00453–L00478) к кандидату + `artifact_path`
   этого отчёта; сквозная трасса `trigger → target → context → claim → verdict →
   delivery` (RC-TRACE-ACCEPT) должна включать ветку `direct_self_correction`.
2. **S7 (релиз/наблюдение):** при деплое релизная политика должна применить
   новую заводскую ревизию `direct.base.l2_writer` (иначе в PG останется прежняя
   активная ревизия и секция канона не поедет); после выката — наблюдение
   реального возражения в чате владельца (в отчёте фиксируется как live-шаг).
3. Не покрыто детерминированно (осознанно): вердикт «источник поддерживает /
   опровергает» — вычисляется моделью по доставленному материалу, но не
   записывается как проверенный факт (см. §3).
4. Смысловая привязка без Reply использует **временной и структурный** базис
   (последний доставленный собственный ответ, число реплик между ним и
   возражением, факт обращения к боту в личном чате/по имени-роли). Fuzzy-поиска
   по теме намеренно нет: по действующей доктрине `quote_resolver` нечёткое
   совпадение ≠ доказанное авторство, а выдуманная тематическая связь нарушила бы
   §12.2 п.1. Цена: один индексированный `SELECT … LIMIT 4` по ledger'у на ход
   без Reply (собственных ответов в базе 1–2 чатов). Факт возражения при таком
   базисе не установлен — это видно в `challenge="unknown"` (§10).

## 10. Исправления по итогам независимого ревью (B1, N2)

Отчёт ревью: `plans/features/evol/reports/rc-v5-selfcorrection-review.md`.
Обе находки исправлены одним патчем, поведение среза не расширено.

### B1 (блокер) — семантическая ветка больше не заявляет возражение

- Файл: `services/direct_chat_service.py`, `_correction_challenge()` (`:3018`)
  используется в `_render_correction_frame` (`:3030`).
- Новый атрибут рамки `challenge="claimed|unknown"`: `claimed` — ТОЛЬКО
  подтверждённый транспортом Reply на конкретную реплику (свою или участника);
  `unknown` — `semantic`, `ambiguous`, `unresolved`.
- В ветке `unknown` текст честный, без утверждения спора:
  - «твой последний доставленный ответ (роль: твои слова; является ли он
    предметом несогласия, по данным НЕ установлено): M3 — «…»»;
  - «текущая реплика человека (роль: очередная реплика, а не установленный
    ответ на твой прежний ответ): M2 — Никита (U1)»;
  - «связь текущей реплики с твоим прежним ответом: …» (вместо «связь
    возражения с предметом»);
  - «статус связи: не установлено, выражает ли текущая реплика несогласие с
    твоим прежним ответом (основание — хронология и структура; Reply нет). Не
    приписывай человеку позицию, которой он не занял, и не начинай спор,
    которого не прозвучало…».
- Слов «возражение»/«оспаривают» в этой ветке нет; в ветке подтверждённого
  Reply формулировки не менялись.
- Фактический payload (личный чат, новый вопрос, ledger: «сегодня в Перми
  дождь»): `link="semantic" subject="own_claim" challenge="unknown"`.

### N2 — цитата слов бота не считается ответом другому участнику

- Файл: `services/direct_chat_service.py`, `_correction_reference_kind()`
  (сравнение `quote_author_id`/автора родителя с `bot_id` → `reference_own_bot`),
  `_correction_counting()` (+ `references_bot`), передача `bot_id` из
  `_build_correction_frame`, строка счёта и атрибут `refs_bot`.
- Счёт печатает «ссылок/цитат на твои прежние реплики (твои слова, не другого
  участника) 1; ответов другим участникам 0», строка списка — «ссылка/цитата на
  твою прежнюю реплику (твои слова, не другого участника)». Категория
  «ответы другим участникам» больше не растёт от собственной цитаты бота.

### Тесты (по одному на находку, падают без исправления)

| Тест | Без исправления |
| --- | --- |
| `test_plain_new_question_without_reply_does_not_claim_challenge` | RED (мутация M7: `challenge` всегда `claimed`) |
| `test_quote_of_bot_words_is_not_answer_to_participant` | RED (мутация M8: убрано сравнение с `bot_id`) |

Существующий `test_semantic_link_is_marked_as_not_reply` не ослаблен: якорь
извлечения метки своей реплики переведён с «оспаривают)» на «установлено)»
(текст этой ветки намеренно изменился), сама проверка (`link`, `semantic`,
claim → `tg:4400`, текст реплики) сохранена.

### Прогоны после исправления

- `tests/test_rc_direct_self_correction.py` — **27 passed**.
- `test_direct_chat` + `test_direct_context_composer_asap3` +
  `test_evol_reply_context_consumers` + `test_evol_reply_context_integrity_seam`
  + мой файл — **337 passed**.
- Широкий `-k` — **17 failed / 1992 passed / 1 skipped**, те же 17
  pre-existing падений, что на базе `33b08401` (см. §6).

Личность/канон и регистрация промпта НЕ тронуты: `services/chat_prompts.py`,
`services/prompt_registry.py`, `services/prompt_migrations.py` в этом патче не
изменялись, печать `44736968bc76` / метка `l2-writer-self-correction-rca1`
прежние.

