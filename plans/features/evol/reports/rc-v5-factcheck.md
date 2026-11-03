# rc/factcheck — отчёт Builder (EVOL-REPLY-CONTEXT-INTEGRITY-01, лейн C+D)

Статус: **готово к независимому ревью** (не к релизу: live-проверок не было).
Дата: 2026-11-04.

## 0. Кандидат и рамки

- Ветка: `rc/factcheck`, база — контракт `e9d4b100` (`plans/features/evol/arch/reply-context-integrity-v5-contract.md`).
- Коммиты: `ba97359d` (код §1–§3), `d6889ff0` (BD-8 тест), `2a0f0519` (паритет маршрута, tool-ключи),
  `1bb33090` (возврат CRLF без изменения содержимого), `ce641fd7` (усиление трёх тестов), далее — этот отчёт.
- Размер содержательного диффа к базе: `factcheck_service.py` 401/64, `factcheck_orchestrator.py` 161/43,
  `factcheck_suitability.py` 220/41, `handlers/factcheck.py` 154/35, `factcheck_planner.py` 57/3,
  `tool_router.py` 18/0, `factcheck_renderer.py` 21/0, `temporal_factcheck.py` 12/3,
  новый контрактный модуль `tests/test_rc_target_media_evidence.py` (719 строк, 29 тестов).
- Что **не** входило в лейн (см. §7): `canonical_context`/`media_marker`/`thread_chain` (Lane A),
  `direct_chat_service` (Lane B), прочие речевые поверхности (Lane E), `prompt_composer` (Lane F),
  схема БД, `config/settings.py`, новые флаги.

## 1. BD-1…BD-9: что закрыто и как

| ID | Закрытие (файл:строка @ `ce641fd7`) | Чем доказано |
| --- | --- | --- |
| BD-1 (тихая подмена Claim в handler v1) | `handlers/factcheck.py:1088–1104`: подмена идёт только как `dataclasses.replace(..., claim_origin="context_window", claim_anchor_tg_message_id, claim_anchor_author, claim_anchor_source, target_source="contextual", target_tg_message_id=<anchor>, text_sufficient=True)` и сразу уходит в `_emit_target_trace`; поля объявлены аддитивно в `ClaimPublication` (`services/factcheck_service.py:602–645`) | `test_handler_declares_contextual_target_in_trace`, `test_contextual_target_is_declared_with_anchor_and_author` |
| BD-2 (envelope собран ДО подмены) | `services/factcheck_orchestrator.py:790–876`: envelope строится после разрешения цели/тезиса, цель берётся эффективная (`:857–859`), `claim_text` в `InputRef` — ровно текст публикации, собранный сверх сохранённой строки (`:871–875`) | `test_v2_envelope_is_built_after_contextual_target`, `test_envelope_claim_matches_publication_and_keeps_target` |
| BD-3 (план по чужим `claim_items`) | `services/factcheck_planner.py:738–769` — `claim_anchor_map` даёт `claim_id → anchor/author/source` без догадок (нет однозначного соответствия → пустой анкор); поле `RetrievalPlan.claim_anchors` (`:316–319`), заполняется в `:983`; событие `factcheck_claim_anchors` (`orchestrator:1103–1122`) | `test_v2_envelope_is_built_after_contextual_target` (план по тому же тексту), `test_envelope_claim_matches_publication_and_keeps_target` |
| BD-4 (ранжирование по `abs(tg−target)`) | `services/factcheck_suitability.py:713–751`: близость — только разрешение ничьей среди семантически равных, два сопоставимых кандидата → `ambiguous` (уточнение), а не «первый ближайший» | `test_semantic_antecedent_beats_nearest_by_tg_id`, `test_antecedent_not_chosen_by_tg_distance`, `test_two_comparable_claims_ask_for_clarification`, `test_handler_answers_clarification_not_verdict` |
| BD-5 (вес «число ответов/длина») | `services/factcheck_suitability.py:462–523`: вес = маркеры спора ×2 + предикат + claim-like + булев факт «на него отвечают»; счётчик ответов и длина текста убраны | `test_dominant_dispute_ignores_reply_count_and_length`, `test_dispute_weight_has_no_reply_count_or_length_terms` |
| BD-6 (текстовый тезис команды превращался в фото-цель) | `handlers/factcheck.py:1030–1040`: adjacent-фото ищется только если в команде нет проверяемого ядра; при ядре цель = сообщение команды | `test_command_with_explicit_thesis_is_not_replaced_by_photo`, `test_text_target_does_not_trigger_adjacent_media` |
| BD-7 (нет `claim_origin` у расшифровки) | `handlers/factcheck.py:1171–1178`: `claim_origin="target_transcript"` в публикации → в `trace_fields` | `test_explicit_text_target_records_source_and_origin` (поля трассы), трасса §5.2 |
| BD-8 (`trigger == target` в deferred) | `services/factcheck_orchestrator.py:657–668`: у возобновления **нет** сообщения-команды — `trigger_tg_message_id=None`, цель остаётся целью | `test_deferred_resume_has_no_phantom_trigger` |
| BD-9 (tool-тезис без происхождения) | `services/tool_router.py:4098–4110` (`claim_origin="tool_claim"`, `claim_truncated`) и `:4247–4260` (ключи payload `claim_origin`, `target_source`, `claim_anchor_tg_message_id`, `claim_truncated` + `stage_event("target_resolve", reason_code="tool_claim")`) | `tests/test_cfg07_guard_tail.py` (`_READY_KEYS`), `test_factcheck_tool_route_cfg06.py`, `test_factcheck_attribution_cfg06.py` |

Отдельно: `claim_origin`/`target_source`/анкор заполняются резолвером публикации (`factcheck_service.py:1114–1125`)
и попадают в envelope (`temporal_factcheck.py:186–189`, `:268–270`, `:540–547`).

## 2. Медиа-предикат и где он гейтит

Единственный предикат — `text_target_sufficient(text)` (`services/factcheck_suitability.py:334–352`):
непустой текст И не сама команда (`_COMMAND_TEXT_RE`) И не консервативный филлер И `has_checkable_core`.
Нового классификатора нет — переиспользованы существующие предикаты.

Гейт — одна точка резолвера, общая для v1/v2/deferred: `services/factcheck_service.py:995–1035`.
При достаточном тексте ассоциация **не предпринимается** (`association_reason="text_claim_sufficient"`,
`association_attempted=False`), `media_ambiguous` не выставляется. Вторая стена (даже если флаг как-то
выставлен) — `ClaimPublication._notice_parts` (`:647–669`): медиа-переспрос только при
`media_ambiguous and not text_sufficient`. Типизация — `association_attempted/status/reason/candidates`,
`media_dependency_source()` (`:691–705`), `target_kind()` (`:707–719`), `notice_reason()` (`:686–689`).

Плюс отдельная развилка handler'а для команды с тезисом (BD-6/M12, `handlers/factcheck.py:1030–1040`).
Инварианты I6–I9 соблюдены: сильные связи (media_group_id, вложение, reply на медиа, альбом) не затронуты —
это проверено `test_album_attachment_still_counts_as_linked_media`, `test_unbound_command_still_attempts_media_association`.

## 3. Матрица техстатусов «код → заголовок»

Источник класса — фактические счётчики стадии: `classify_retrieval` (`factcheck_service.py:1198–1242`),
для envelope-ветки — `envelope_retrieval_state` (`:1332–1351`); код причины — `_RETRIEVAL_REASON`
(`:1144–1150`); код заголовка — `factcheck_renderer.headline_code` (`:236–254`).

| §11.2 | Условие (факт) | Класс | reason | headline |
| --- | --- | --- | --- | --- |
| 1 провайдер недоступен | `used==0 and (attempted>0 or failures>0)` | `search_failed` | `provider_unavailable` | `technical:provider_unavailable` |
| 2 дедлайн | `budget_exhausted and used==0` (+ `fetch_skipped_deadline>0`) | `budget_exhausted` | `deadline_exceeded` | `technical:deadline_exceeded` |
| 3 парсер реально упал | `used>0 and fetch_errors>0` | `processing_failed` | `source_missing` | `technical:source_missing` |
| 4 пустая выдача | `used==0 and empty_results>0` | `no_usable_results` | `insufficient_evidence` | `verdict:insufficient_evidence` |
| 5 нерелевантно | `used==0 and irrelevant_results>0` | `no_usable_results` | `insufficient_evidence` | `verdict:insufficient_evidence` |
| 6 читаемо, но нечего цитировать | `used>0`, `refs_collected==0`, есть `search_text` | `no_usable_results` | `insufficient_evidence` | `verdict:insufficient_evidence` + `_RETRIEVAL_NO_CITABLE_NOTICE` (`orchestrator:1173–1184`) |
| 7 достаточно для условного разбора | есть evidence | `ok` | – | из `factual_verdict` |
| 8 смешанный прогон | части с разными статусами | – | – | `verdict:*` / `parts:*`; техзаголовок снимается для содержательного вердикта |
| 9 vision pending/failed | `image_unchecked`/`vision_failed` | – | – | только при реальной медиа-зависимости |

ES-1/ES-2 (выдуманный `PROCESSING_FAILED` из «нет URL») закрыты в `:1233–1239` и `envelope_retrieval_state`;
ES-3 (`fetch_skipped_deadline`) — `factcheck_planner.py:1619–1627`, `:1720–1725`, поле `:1179–1184`, отдача `:1737`;
ES-4 — `orchestrator:1174–1184` (оговорка и при `insufficient_evidence`); ES-5 — медиа-оговорка не формируется,
когда её нет (`_notice_parts`).
ES-6 из контракта был помечен как «дефект не доказан, нужен тест»: **закреплён тестом без изменения кода** —
`test_mixed_run_headline_does_not_contradict_successful_part` (заголовок `verdict:mixed`, техфразы «материалы
не удалось разобрать» в видимом тексте нет). Код подавления не понадобился — расхождения нет.

## 4. Поля трассы

`ClaimPublication.trace_fields()` (`factcheck_service.py:721–746`):
`target_source`, `target_kind`, `target_tg_message_id`, `claim_origin`, `claim_anchor_tg_message_id`,
`claim_anchor_source`, `text_claim_resolved`, `media_expected`, `media_dependency_source`,
`association_attempted/status/reason`, `association_candidates` (число), `linked_media_ids`,
`media_notice_emitted`, `media_notice_reason`. Только коды и ID, без текстов (§7 контракта).

`evidence_diagnostics()` (`:1259–1309`): `source_query_count`, `provider_attempts/failures`,
`documents_retrieved`, `queries_with_results`, `extract_attempts/successes/failures`, `empty_results`,
`irrelevant_results`, `off_topic_sources_dropped`, `relevant_evidence_count`, `citable_evidence_count`,
`budget_exhausted`, `fetch_skipped_deadline`, `retrieval_class`, `technical_reason`; неизвестное — `"н/д"`,
а не 0 (`_diag_count:1249–1256`).

`emit_target_trace` (`:1353+`) и `headline_code` (`renderer:236–254`) дают сквозную цепочку
`trigger → target_resolution → claim_origin/anchor → plan claim_ids → retrieval counts → verdict.reason →
headline_code → delivery.reply_to`; образец — `plans/features/evol-reply-context-integrity-01/evidence/trace-factcheck-target.txt`.

## 5. Покрытые требования `requirements-map.json`

Покрытие **частичное и заявлено как частичное**: в карте 355 строк, из них по лейнам
RC-TARGET-ANCHOR 41, RC-CONTEXT-CLAIM 31, RC-MEDIA-OPTIONAL 27, RC-EVIDENCE-STATUS 27.
Тестами этого лейна адресованы 41 id (по docstring-привязке в `tests/test_rc_target_media_evidence.py`):

- **RC-TARGET-ANCHOR (13):** RC-TGT-INVARIANT, RC-DEF-TARGET, RC-TGT-EXPLICIT-REPLY, RC-TGT-EXPLICIT-HINT,
  RC-TGT-NO-REWRITE, RC-TGT-NO-FABRICATED-ID, RC-TGT-SEM-STRUCT, RC-TGT-SEM-AMBIG, RC-TGT-SEMANTIC-CORE,
  RC-TGT-UNB-CLARIFY, RC-TGT-UNB-NOHEURISTIC, RC-S009, RC-S010.
- **RC-CONTEXT-CLAIM (4):** RC-DEF-CLAIM, RC-CLM-TARGETREF-CONTINUITY, RC-CLM-PLAN-FROM-CLAIM, RC-S019.
- **RC-MEDIA-OPTIONAL (14):** RC-MED-ALL-ROUTES, RC-MED-DATA-TRUTH, RC-MED-LINKED, RC-MED-NOTICE-SCOPE,
  RC-MED-RELATION-NOT-PRESENCE, RC-MED-TEXTCMD, RC-MED-TEXTONLY, RC-MED-TYPED-AMBIG, RC-MED-UNBOUND,
  RC-S032, RC-S033, RC-S038, RC-S041, RC-S043.
- **RC-EVIDENCE-STATUS (10):** RC-EVS-PROVIDER-DOWN, RC-EVS-DEADLINE, RC-EVS-EXTRACT-FAILED,
  RC-EVS-EMPTY-RESULT, RC-EVS-NO-RELEVANT, RC-EVS-NO-CITABLE, RC-EVS-MIXED-RUN, RC-EVS-NO-GUESS,
  RC-EVS-ONE-FACT-ONE-EXPL, RC-EVS-DIAG-COUNTERS.

RC-SPEECH-BOUNDARY, RC-CONTEXT-FIDELITY, RC-DIRECT-SELFCORR и большинство RC-TRACE-ACCEPT **не покрыты**
(это лейны A/B/E/F). Статусы в карте не менял — их связывает PM/Reviewer по факту ревью.

## 6. Проверки и мутации

Тесты на финальном кандидате (`ce641fd7`, Python 3.12, `pytest -q -p no:cacheprovider`):

| Набор | Результат |
| --- | --- |
| 30 файлов: контрактный модуль + `factcheck_service/handlers/gate/context/attribution/media/tool_route/post_release/prompts/wide_context/grounding/fc_r1/two_call/w6/w7/asap8_b07`, `test_evol_factcheck_critical`, `test_factcheck_p0_fc`, `test_evol_vision_sync_core/wave2`, `test_factcheck_deep_context_round1023`, `test_cfg07_guard_tail`, `test_native_reply_media_context_round1024` | **651 passed, 0 failed**, 41 s |
| Сам контрактный модуль | **29 passed** |

Предыдущие независимые прогоны того же среза: 485 passed (18 файлов) и 163 passed (12 файлов) — новых падений
нет. Пред-существующие падения против базы `b8ea1d8c` (полный прогон, `runs/rc-factcheck-trace/fails-*.txt`):
84 проблемы на базе → 81 на кандидате; единственная запись, которая была красной тогда и относится к моему
срезу (`test_factcheck_fc_r1_fix.py::TestRelevanceCascade::test_all_irrelevant_is_honest_failure`), на
`ce641fd7` **зелёная** (проверено отдельным запуском). Остальные расхождения — `test_initiative_coordination.py`
(3 теста) и `test_youtube_multimodal_download_round1024.py` (сбои сбора) падают одинаково на базе и кандидате,
то есть пред-существующие и вне лейна.

Мутации (батч из 7, скрипт в рабочей области, воспроизводит запрещённые контрактом дефекты; «убит» = набор краснеет):

| Мутация | Вердикт |
| --- | --- |
| E1 снят медиа-гейт (текстовая цель ищет соседнее фото) | убит |
| E2 любой `used>0` = поломка парсера | убит |
| E3 медиа-оговорка игнорирует достаточность текста | убит |
| E4 вес антецедента по длине текста | убит |
| E5 ближайший по tg-id побеждает семантику | убит |
| E6 команда с тезисом становится фото-целью | убит |
| E7 contextual-подмена не объявлена | убит |

Честно: первый батч дал 4/7 — E4, E5, E7 выживали, потому что три теста не доказывали контракт
(проверяли структурную ветку вместо правила выбора, а подмена объявлялась только на уровне резолвера).
Тесты усилены в `ce641fd7` (инвариантность веса к числу ответов и длине; семантика против ближайшего id;
объявление contextual-цели в трассе хендлера), после чего 7/7. Это изменение тестов, а не ослабление проверок.

## 7. Что сознательно не сделано

1. **ES-6** закрыт тестом (см. §3), кода не менял — контракт это прямо допускал.
2. **Лейн A/B/E/F не тронуты**: `canonical_context`, `media_marker`, `thread_chain`, `direct_chat_service`,
   `prompt_composer`, `summary_memory`, `initiative_observer`, `meme_initiative`, `lore_compiler` — речевая
   проекция (`SpeechProjection`, метки `M*/U*`) не реализована; RC-SPEECH-BOUNDARY / RC-CONTEXT-FIDELITY /
   RC-DIRECT-SELFCORR открыты.
3. **Пункты §8 контракта 1–5** (разделение media/evidence в публичном DTO, per-claim `retrieval_state`,
   строка времени в FactCheck-payload, имя автора цитаты в `format_chain_line`, пометка о вытеснении окна)
   не делались: это Lane A либо смена замороженной схемы.
4. **Флаги, БД, `config/settings.py`** не менялись; новых LLM-вызовов, регенераций и regex-чистки текста нет.
5. **Live/прод-проверок не было**: деплой не выполнялся, реальный Telegram-прогон не запускался.
   Полевое поведение (публикации в бою) не проверено — это вне лейна и требует отдельного релиза.
6. **Генератор трассы** `trace_run.py` остался в рабочей области, в репозиторий положен только его вывод;
   воспроизведение — ручной запуск, а не тест. Для строгой привязки evidence это стоит учесть.

## 8. Риски и побочные находки

- **Изменение адреса доставки при contextual-цели** (`tests/test_factcheck_media_2026_10_25.py:910–918`):
  Reply теперь уходит на сообщение-команду (триггер), а не на пустое сообщение-цель. Это I5 контракта,
  но для пользователя это видимое изменение — прошу Reviewer проверить осознанность.
- **Смена смысла техстатуса**: «нашёл, но ссылок нет» больше не печатает «материалы не удалось разобрать».
  Ожидаемо по §11.2 п.6, но формулировки вердикта теперь мягче — проверять на реальных прогонах.
- **Переводы строк**: `2a0f0519` переписал `factcheck_service.py` и `factcheck_orchestrator.py` в LF, тогда как
  репозиторий держит их CRLF; реальный дифф 401/64 превращался в 5548/1527 строк. Возвращено в `1bb33090`
  без изменения байтов кода. На будущее: писать эти файлы в CRLF.
- **`pytest.ini` объявляет `timeout`/`timeout_method`, но `pytest-timeout` в окружении не установлен** —
  пред-существующее: таймауты тестов здесь фактически не работают (предупреждение Unknown config option).
- **`test_initiative_coordination.py`**: 3 теста красные и на базе, и на кандидате — пред-существующее,
  не связано с фактчеком (`incidentially found`, `unrelated/pre-existing`).
- Мелкое: `_dominant_dispute` по-прежнему даёт `+1` за факт «на него отвечают» — это структурный факт связи,
  а не счётчик ответов; в отчёте отмечаю явно, чтобы это не выглядело остатком BD-5.

## 9. Итог

BD-1…BD-9 закрыты по коду и закреплены тестами; медиа-опциональность проведена одним предикатом через общий
резолвер; техстатусы выводятся из фактических счётчиков стадии, ES-6 закреплён тестом без правки кода;
мутации 7/7. Требования лейнов A/B/E/F и live-проверки остаются открытыми и не выдаются за сделанные.
