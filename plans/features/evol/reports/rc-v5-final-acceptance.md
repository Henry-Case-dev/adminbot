# RC v5 — финальная приёмка 120 сценариев (независимый Reviewer)

- Кандидат: ветка `evol/impl`, коммит `4baccb1d3e310bfdaf019c06cab69cca5d620539` (база `65bdeeee`).
- Код `services`/`handlers`/`tests` в этом кандидате байт-в-байт равен одобренному дереву `e02335f9`
  (`git diff --name-only e02335f9 HEAD` даёт только `plans/`, `web/` и UI-тесты версионирования промптов).
  Срезы `ed939222/4f32ea8d` (шов), `44364e83` (потребители), `bfa26e60` (фактчек), `e02335f9` (самокоррекция) — предки.
- Источник владельца: `plans/owner_inputs/2026-11-03-evol-reply-context-integrity-v5.md` (§13 — 120 сценариев).
- Карта: `plans/features/evol-reply-context-integrity-01/requirements-map.json` (312 строк: 57 VERIFIED / 255 PENDING,
  `candidate_commit` = `bfa26e60`).

## Вердикт: **Needs Fixes**

Приёмка 120 сценариев не пройдена. Блокируют не косметические пункты, а отсутствие действительной трассы
(§7/§11.3) и неразвёрнутая сверка карты/гейта на этом кандидате, плюс три Related-small дефекта понимания,
которые владелец относит к P0-классу.

## Три линии доказательств

- **Implementation.** Проверены на этом кандидате: шов `services/canonical_context.py` (`format_speech_item`,
  `SpeechProjection`, `SpeechRelation`, `SpeechQuote`), окно/усечение `services/chat_context.py`,
  `direct_chat_service._build_user_content/_render_thread/_correction_*`, `direct_l1.render_window_lines` и
  `build_l2_plan_block`, `handlers/factcheck.py:226-487`, `factcheck_context.build_factcheck_context`,
  `factcheck_service.classify_retrieval/evidence_diagnostics`, `summary_memory.build_rag_context`,
  `tool_router._history_lines`, `meme_initiative._default_summarize`, `lore_compiler_service._graph_facts`,
  `thread_chain.collect_thread_chain/render_reply_chains`.
- **Test validity.** Прочитаны утверждения (не имена) `test_evol_reply_context_consumers.py` (53 теста),
  `test_rc_target_media_evidence.py` (31), `test_rc_direct_self_correction.py` (27), `test_evol_reply_context_integrity_seam.py`.
  Они проверяют фактический текст payload: отсутствие `tg:/msg:/fact:`/`[uid]`, сохранность абсолютных дат, forward,
  `(бот)`, `↳ Reply M`, обратную карту метки в ID и ветку OFF (сырой канон). Слабые места названы в таблице
  (сц. 38 — тест допускает `status=missing`; сц. 99/115 — утверждений про рёбра окна нет).
- **Independent challenge.** Свои прогоны (`WorkspaceData/runs/rc-v5-final/`): перемешанные ветки с Reply через старый
  тред, две «Ирина» и смена ника, цитата без Reply, два чата, Composer ON/OFF и рубильник речи OFF, фактчек-фид
  «волокна vs гибриды», suitability-гейт, рестарт на свежем SQLite, тесный бюджет с reply-цепочкой, старый/новый факт,
  мем/летописец/инструменты.

## Индекс доказательств payload-ов

| Ключ | Что снято | Файл |
| --- | --- | --- |
| P-DIR1 | Direct: Reply на сообщение вне окна (tg:6090), перемешанные ветки, две «Ирина», смена ника, второй чат | `WorkspaceData/runs/rc-v5-final/stage1.txt` |
| P-DIR2 | Цитата без Reply (Composer ON / Composer OFF / рубильник речи OFF) | `stage2.txt` |
| P-FC1 | Фактчек-фид по умолчанию (метки, reply_chains) и фид suitability-гейта (без проекции) | `stage3.txt` |
| P-RST | Рестарт: свежий процесс, SQLite, окно и цепочка 8004-8002-8001, обратная карта | `stage4.txt` |
| P-MSC | Усечение окна и цепочки, RAG старый/новый факт, инструменты, мем, летописец | `stage5.txt` |

Ключевые фрагменты (дословно):

    P-DIR1 <Conversation_Branch>
           [31.10.2025 12:26 | Пётр (U1) | M1]: исходный тезис про волокна
           [01.11.2025 12:29 | Алиса (U2) | M2]: бот, разбери это ↳ Reply M1
           ... <Global_Context> ... «Ирина (U2)» vs «Ирина (#8003) (U3)» ...
           ref_leak=[] uid_leak=[] other_chat_leak=False
           reverse_map M1->tg:6090 ... M8->tg:6106
    P-DIR2 [01.11.2025 12:30 | Алиса (U3) | M3]: а это правда? <<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]
           цитата (автор: автор цитаты не определён): «билет 500» — выделенный фрагмент, оригинал недоступен
    P-FC1  [01.11.2025 12:26 | Васек (U4) | M5]: там ещё волокна разные ...
           <reply_chains ...> [12:21 | Хан (U1) | M2] ... ↳ Reply M2     raw_refs=[]
           gate-фид: [12:16 | Хан | tg:6990] ...  (raw_refs=tg:6990..7005, labels=[])
    P-RST  window_rows=6; chain items tg:8004->tg:8002->tg:8001, авторы Хан/Васек/Хан, метки те же в окне и цепочке
    P-MSC  budget=700: chain в блоке и «часть окна не показана (10)»; budget=420/380/300: chain=НЕТ, пометки про цепочку нет
           RAG: [dream] [09.2024 | Ирина | F1] ... (возможно устарело) / [dream] [10.2025 | Ирина | F2] ...
           мем: ids=['M15','M16'], тексты ['привет','пока']

## Таблица 120 сценариев

Статусы: **PASS** — есть конкретное наблюдение; **FAIL** — наблюдение противоречит требованию; **NOT PROVEN** — доказательства нет.

| # | Сценарий | Статус | Наблюдение / доказательство |
| --- | --- | --- | --- |
| 1 | §13.1 | **PASS** | T test_antecedent_not_chosen_by_tg_distance; C factcheck_suitability (нет выбора по модулю tg-id); P-FC1: цель M5 (Васек) при шумной ветке гибридов |
| 2 | §13.2 | **PASS** | P-FC1: тезис = M5 Васек, ребро «↳ Reply M2» на вопрос Хана, гибриды M3/M4 в фоне; цель не смещена |
| 3 | §13.3 | **PASS** | T test_semantic_antecedent_beats_nearest_by_tg_id; T test_contextual_target_is_declared_with_anchor_and_author (basis=semantic) |
| 4 | §13.4 | **PASS** | T test_two_comparable_claims_ask_for_clarification; T test_handler_answers_clarification_not_verdict |
| 5 | §13.5 | **PASS** | P-DIR1: цепочка 6107-6090 взята по Reply, хотя окно 6101..6106 перемешано; T test_antecedent_not_chosen_by_tg_distance |
| 6 | §13.6 | **PASS** | P-DIR1: родитель tg:6090 (на сутки старше окна) восстановлен из БД, branch/thread с «↳ Reply M1»; P-RST: 8004-8002-8001 в свежем процессе |
| 7 | §13.7 | **PASS** | Re-check 1: смысловая связь строится в проде (`factcheck_suitability._semantic_link`) на обоих маршрутах; в фактическом payload «↳ по теме M3 (не Reply)» (трасса + мой прогон); structural/tiebreak не помечаются; T test_semantic_antecedent_is_marked_not_reply, test_structural_antecedent_stays_silent_about_semantics |
| 8 | §13.8 | **PASS** | P-FC1: триггер 7005 даёт цель 7004 по reply_to_id из БД; R-FC: без полного reply_to_message цель восстанавливается ровно по id |
| 9 | §13.9 | **PASS** | T test_handler_answers_clarification_not_verdict; пустая цель уходит в контекстный поиск, угадывания нет (R-FC) |
| 10 | §13.10 | **PASS** | T test_two_comparable_claims_ask_for_clarification (два равных кандидата дают уточнение) |
| 11 | §13.11 | **PASS** | T test_command_with_explicit_thesis_is_not_replaced_by_photo: проверен текст команды 913791, не картинка |
| 12 | §13.12 | **PASS** | P-DIR1: uid 88001 под алиасом «Алиса (U2)», 88003 «Ирина (U3)»; P-DIR1b без алиасов: «Ирина (U2)» против «Ирина (#8003) (U3)» — не слиты |
| 13 | §13.13 | **PASS** | P-DIR1: рамка различает «предмет возражения (слова человека, не твои)» и свои слова; T test_reply_to_participant_is_not_own_claim |
| 14 | §13.14 | **PASS** | P-DIR2: «цитата (автор: автор цитаты не определён)» — не выдумано; R-CO F1: «цитата (автор: Пётр (U3))» |
| 15 | §13.15 | **PASS** | C factcheck_suitability/_dominant_dispute без веса по длине и числу ответов; T test_dominant_dispute_ignores_reply_count_and_length |
| 16 | §13.16 | **PASS** | R-FC: атомизация claims и claim_anchors на фрагмент; T test_v2_envelope_is_built_after_contextual_target |
| 17 | §13.17 | **PASS** | R-FC: claim_type/verifiable отделяют оценку от проверяемой части (factcheck_suitability) |
| 18 | §13.18 | **NOT PROVEN** | Альбом с caption на другом элементе покрыт (T test_album_attachment_still_counts_as_linked_media), но voice/транскрипция и форвард без даты в payload не наблюдались |
| 19 | §13.19 | **PASS** | T test_contextual_claim_from_chain_keeps_its_own_date_and_author; R-FC B2: дата и автор анцедента не подменяются датой реакции |
| 20 | §13.20 | **PASS** | P-DIR1: роли «кто спросил / кто ответил / к кому обращаются» (U2, U3, Target_User) различны; T test_l2_payload_has_four_roles_and_canon |
| 21 | §13.21 | **NOT PROVEN** | Нет наблюдения, что отсылка к «Лёхе и волокнам» не выдумывается при отсутствии данных памяти |
| 22 | §13.22 | **NOT PROVEN** | Нет наблюдения, что достоверный факт памяти влияет только на тон и не подменяет объект проверки |
| 23 | §13.23 | **PASS** | C handlers/factcheck.py:432-435,484-487: ошибка БД или цепочки даёт пустой блок, цель не меняется; R-CO F3: пометка N при тесном бюджете |
| 24 | §13.24 | **PASS** | R-FC: оба маршрута (handler v1 и v2) и deferred сохраняют цель; P-FC1 снят в дефолтной конфигурации флагов |
| 25 | §13.25 | **NOT PROVEN** | Параллельные прогоны в двух чатах не наблюдались (нет теста и прогона) |
| 26 | §13.26 | **PASS** | Re-check 1: трасса снята реальным прогоном закоммиченного скрипта: два моих прогона и файл в репозитории один sha256 24b67a25… (5376 симв.); счётчики согласованы (provider_attempts = фактические вызовы: 2/2, 0/0, 2/2…), все стадии 1/7..7/7, неисполненное названо |
| 27 | §13.27 | **NOT PROVEN** | Нет прогона на окне в сотни сообщений; новых LLM-вызовов нет (T test_no_new_llm_call_or_regeneration), но часть про DB-сканирования не измерена |
| 28 | §13.28 | **PASS** | Тесты и пробы на произвольных именах и ID (Алиса/88001, 8001..8010); в services и handlers нет ветвлений по словам инцидента (grep) |
| 29 | §13.29 | **PASS** | 381 целевой тест зелёный на HEAD (factcheck, target-media, direct, consumers, seam, summary, tool_router, history); ранее 910 по профилю — регрессий нет |
| 30 | §13.30 | **PASS** | Это ревью: сняты фактические payload-ы и reply_to_id (P-DIR1, P-DIR2, P-FC1), не только зелёные моки |
| 31 | §13.31 | **PASS** | T test_text_target_does_not_trigger_adjacent_media: media_ambiguous=False, association_attempted=False, notice() без требования картинки |
| 32 | §13.32 | **PASS** | T test_media_ambiguity_not_shown_over_sufficient_text: при text_sufficient=True уведомление не выводится |
| 33 | §13.33 | **PASS** | T test_command_with_explicit_thesis_is_not_replaced_by_photo |
| 34 | §13.34 | **NOT PROVEN** | Reply на фото без текста: реального Vision/OCR не запускали, порядок media_pending до no_claim не наблюдался |
| 35 | §13.35 | **PASS** | T test_album_attachment_still_counts_as_linked_media: media_group_id и caption на другом элементе, media_expected=True |
| 36 | §13.36 | **NOT PROVEN** | Mixed текст и распознанное фото: содержимое обоих в payload не наблюдалось (Vision не запускался) |
| 37 | §13.37 | **NOT PROVEN** | Mixed с упавшим чтением изображения: частичная проверка текста и честная оговорка не наблюдались |
| 38 | §13.38 | **NOT PROVEN** | T test_unbound_command_still_attempts_media_association допускает status=missing: «единственный надёжный кандидат проверяется» не доказано |
| 39 | §13.39 | **PASS** | T test_media_ambiguity_not_shown_over_sufficient_text (вторая часть): без текста и с двумя кандидатами — уточнение, кандидаты в трассе |
| 40 | §13.40 | **PASS** | P-FC1: текстовая цель без фото даёт media_notice_emitted=False, ассоциация не запускается; T test_text_target_does_not_trigger_adjacent_media |
| 41 | §13.41 | **NOT PROVEN** | Отложенный фактчек по связанному фото через рестарт не наблюдался |
| 42 | §13.42 | **NOT PROVEN** | v1/v2/deferred — одна политика (R-FC), но инструментальный маршрут не проверен (открытый GAP-TOOL-ROUTE) |
| 43 | §13.43 | **PASS** | T test_album_attachment_still_counts_as_linked_media: альбом, привязанный Reply к тексту, остаётся проверяемым без слова «фото» |
| 44 | §13.44 | **PASS** | T test_evidence_status_matrix_matches_real_counters[provider_unavailable] и [deadline_exceeded]: класс из фактических счётчиков |
| 45 | §13.45 | **PASS** | T test_evidence_status_matrix_matches_real_counters[insufficient_evidence, empty_results=2]: пустая выдача не равна сбою разбора |
| 46 | §13.46 | **PASS** | T test_evidence_status_matrix_matches_real_counters[insufficient_evidence, irrelevant_results=2]: нерелевантные документы не дают source_extract_failed |
| 47 | §13.47 | **NOT PROVEN** | Реальный сбой извлечения при уже привязанной ссылке даёт class=ok и пустой reason (открытый N2 карты) — честный техстатус с реальной трассой не доказан |
| 48 | §13.48 | **PASS** | T test_internal_search_without_urls_is_not_a_parser_break: текст без ссылок даёт insufficient_evidence, не поломку |
| 49 | §13.49 | **PASS** | T test_mixed_run_headline_does_not_contradict_successful_part: headline=verdict:mixed, «не удалось разобрать» отсутствует |
| 50 | §13.50 | **NOT PROVEN** | Условный содержательный разбор при недостатке источников — поведение модели; живого прогона нет, а артефакт трассы недействителен |
| 51 | §13.51 | **NOT PROVEN** | Совместный рендер нескольких Telegram-чанков (без повторных notices) не наблюдался |
| 52 | §13.52 | **PASS** | R-FC и P-FC1: target_kind, media_dependency_source, media_notice_emitted заполнены фактическими значениями в обоих маршрутах |
| 53 | §13.53 | **PASS** | P-DIR1: 3 и более разных Telegram ID в контексте, в тексте payload нет ни tg:/msg:, ни [uid] (ref_leak=[], uid_leak=[]) |
| 54 | §13.54 | **PASS** | P-DIR1 и P-RST: произвольные имена и ID (Алиса/88001, 8001..8010), не совпадающие со скриншотом |
| 55 | §13.55 | **PASS** | P-DIR1: край «↳ Reply M1» — метка, а доставка идёт по реальному target_message_id (код доставки не менялся) |
| 56 | §13.56 | **PASS** | P-DIR2: без Reply нет фиктивного ребра, честное «связь не подтверждена» (direct_l1.py:1770) и challenge=unknown в рамке |
| 57 | §13.57 | **PASS** | P-MSC RAG: «[dream] [10.2025 | Ирина | F2]: …», fact: не печатается |
| 58 | §13.58 | **PASS** | T test_support_is_visible_and_trace_id_stays_machine_side: факт, дата, автор, ссылка есть; run_id в payload нет |
| 59 | §13.59 | **PASS** | Тот же тест: claim и evidence[url, published_at, source_kind], внутренние ключи не выводятся |
| 60 | §13.60 | **PASS** | C direct_chat_service.py:12870-12956: окно и план инициативы на одной проекции, адресат именем; R-CO подтверждает живым прогоном |
| 61 | §13.61 | **PASS** | P-MSC: RAG и память идут через format_speech_item, tg:/fact: превращаются в M/F; T test_legacy_rag_structure_also_speaks |
| 62 | §13.62 | **PASS** | P-DIR1: «билет стоит 500 рублей» дословно в payload; чистки цифр нет (в диффе нет re.sub по исходящему тексту) |
| 63 | §13.63 | **NOT PROVEN** | Вопрос про SQL/JSON/ID: разрешающая лексика в каноне есть, фактического ответа не наблюдали |
| 64 | §13.64 | **PASS** | RBAC-канал диагностики не тронут диффом; представление explicit_admin_diagnostic предусмотрено (canonical_context.py:326-333) |
| 65 | §13.65 | **NOT PROVEN** | Запрос ссылки на конкретное сообщение: фактическая выдача URL/ID не наблюдалась |
| 66 | §13.66 | **PASS** | P-DIR1 и P-RST: одинаковые имена и фразы разных людей различаются метками (U2 против U3; U1 против U4) |
| 67 | §13.67 | **PASS** | P-DIR2 A/B/C: Composer ON, Composer OFF и рубильник речи OFF дают те же отношения без raw id в речи; T — обе ветки |
| 68 | §13.68 | **PASS** | C: id живёт в структурном слое, текст участника не редактируется; в диффе нет regex-чистки; P-DIR1 сохраняет «500 рублей» |
| 69 | §13.69 | **PASS** | P-MSC: payload мема ids = [M15, M16], тексты неизменны; промпты мема в диффе не менялись |
| 70 | §13.70 | **PASS** | T test_search_route_speaks_and_keeps_reverse_map (пары метка в ID в защищённом событии); T test_no_new_llm_call_or_regeneration; regex-чистки и перегенерации нет |
| 71 | §13.71 | **PASS** | T test_one_question_and_two_quotes_is_one_not_three |
| 72 | §13.72 | **PASS** | T test_three_real_questions_are_three |
| 73 | §13.73 | **PASS** | T test_two_questions_in_one_message_are_not_two_messages |
| 74 | §13.74 | **PASS** | R-SC живой прогон S1: признаёт именно единицу счёта; T test_counting unit-тесты |
| 75 | §13.75 | **PASS** | R-SC живые S1/S4; T test_own_previous_answer_is_not_evidence |
| 76 | §13.76 | **PASS** | R-SC S6: аргументированное несогласие воспроизводится (стохастика модели отмечена) |
| 77 | §13.77 | **PASS** | R-SC S4: «твоих реплик в видимой истории нет, посчитать не могу»; T test_window_coverage_is_stated |
| 78 | §13.78 | **PASS** | R-SC S2: 3 из 3 прочтений «Тест Тьюринга провален» как оценки поведения |
| 79 | §13.79 | **PASS** | R-SC S3: буквальный вопрос получает ответ по теме |
| 80 | §13.80 | **PASS** | T test_canon_reads_indirect_critique_and_keeps_literal_questions; T test_plain_new_question_without_reply_does_not_claim_challenge |
| 81 | §13.81 | **PASS** | T test_canon_allows_justified_disagreement_and_honest_uncertainty |
| 82 | §13.82 | **PASS** | T test_plain_new_question_without_reply_does_not_claim_challenge и B1 re-review: семантика помечена «НЕ Reply», challenge=unknown |
| 83 | §13.83 | **PASS** | P-DIR1: рамка ссылается на подтверждённый Reply (link=telegram_reply), шумная ветка целью не стала |
| 84 | §13.84 | **PASS** | T test_reply_to_participant_is_not_own_claim и test_quote_of_bot_words_is_not_answer_to_participant: чужое не присваивается |
| 85 | §13.85 | **PASS** | C _correction_challenge: Reply на чужую реплику даёт subject=participant, не обвинение бота |
| 86 | §13.86 | **PASS** | T test_canon_forbids_invented_algorithm_knowledge |
| 87 | §13.87 | **NOT PROVEN** | Авторизованная диагностика с реальной метрикой или кодом алгоритма: фактического ответа не наблюдали |
| 88 | §13.88 | **PASS** | T test_canon_reads_indirect_critique_and_keeps_literal_questions; R-SC S2 (социальный сигнал без выдуманных фактов) |
| 89 | §13.89 | **NOT PROVEN** | Удержание исправленной версии на следующем ходу (cross-turn) не наблюдалось |
| 90 | §13.90 | **NOT PROVEN** | Отсутствие «долговременного урока» после одной реплики: теста и наблюдения нет |
| 91 | §13.91 | **PASS** | T test_canon_keeps_persona_and_ownership; R-SC живые ответы сохраняют тон, юмор и допустимую резкость |
| 92 | §13.92 | **PASS** | Нет специальных if под показанный диалог (grep services и handlers); тесты на произвольных именах и темах |
| 93 | §13.93 | **PASS** | P-DIR2 A/B/C: Composer ON/OFF дают те же отношения, отправитель не путается, raw refs нет |
| 94 | §13.94 | **PASS** | P-DIR1 (Reply), P-DIR2 (нет Reply), P-RST (старый тред): различие реальной и смысловой связи, честное «не установлено» |
| 95 | §13.95 | **PASS** | Это ревью: сравнены авторитет источника (человек, бот, цитата, evidence), блоки промпта и итоговая речь |
| 96 | §13.96 | **PASS** | T test_no_new_llm_call_or_regeneration; в диффе нет новых LLM-вызовов, бюджетов и второго движка |
| 97 | §13.97 | **PASS** | P-DIR1: две «Ирина» (88001 и 88003) дают U2 и U3, биографии не слиты; P-RST: два «Хан» (99001 и 99004) дают U1 и U4 |
| 98 | §13.98 | **PASS** | P-DIR1: старые сообщения 88001 показаны актуальным алиасом «Алиса», слияния с однофамильцем нет |
| 99 | §13.99 | **PASS** | Re-check 2 (`fb761f73`): реальная SQLite + `db.get_messages_around` + `build_chat_context` и `_build_user_content` (композер ON и OFF) — подтверждённое ребро печатается (`↳ Reply M1` у M4, `↳ Reply M3` у M8); сосед по теме без Reply, декой (`reply_to_id` = `id` чужой строки БД) и родитель вне окна рёбер не получают; на коде `ff13141d` тот же набор строк давал ЛОЖНОЕ ребро у декоя |
| 100 | §13.100 | **PASS** | P-DIR2: цитата без Reply отрисована как «цитата (автор: автор цитаты не определён): билет 500», фиктивного Reply нет |
| 101 | §13.101 | **PASS** | P-DIR1: автор (U2), адресат (Target_User) и упомянутый (U3) — три разные роли |
| 102 | §13.102 | **NOT PROVEN** | Семантическая связь через 50-100 сообщений без Reply не наблюдалась |
| 103 | §13.103 | **PASS** | P-DIR1: два параллельных разговора, ложных Reply-рёбер нет (ребро только подтверждённое) |
| 104 | §13.104 | **PASS** | P-DIR1 и P-RST: абсолютные даты «31.10.2025 12:26», «01.11.2025 14:40» сохранены, порядок по timestamp; живого ответа «что было до/после» не снимали |
| 105 | §13.105 | **PASS** | P-MSC: старая и новая формулировки факта обе с датой и provenance, старая помечена «возможно устарело» |
| 106 | §13.106 | **PASS** | P-MSC: «[dream] [10.2025 | Ирина | F2]» — содержимое, автор, дата, метка; fact:77 не просачивается |
| 107 | §13.107 | **NOT PROVEN** | Воспоминание из другого чата с ограничением доступа: scope не проверялся |
| 108 | §13.108 | **PASS** | T test_dedup_key_is_structural_in_both_forms; P-RST: одинаковые фразы разных людей не слиты |
| 109 | §13.109 | **PASS** | P-DIR1 и P-RST: manifest items/participants дают точное соответствие метки реальному ID; Re-check 2 (`fb761f73`): оба маршрута фактчека (`resolve_context_claim`, `_run_inner`) эмитят `speech_projection`, все метки фида (M1..M3, U1..U3) покрыты картой, MISSING=[] |
| 110 | §13.110 | **PASS** | P-DIR2 A/B/C: speaker, reply, quote, timestamp и provenance идентичны, различается только публикация метки |
| 111 | §13.111 | **PASS** | Re-check 1: при 420/380/300 в блоке «…цепочка ответов не показана (2)» с точным N шагов, в логе omitted_chain=2, длина блока ≤ бюджета (398/329/260), потолок 1200 не вырос |
| 112 | §13.112 | **NOT PROVEN** | Память и RAG сохраняют автора, дату и provenance (P-MSC), но сборка саммари и истории не прогонялась |
| 113 | §13.113 | **PASS** | T test_support_is_visible_and_trace_id_stays_machine_side: содержание, дата, автор и источник видны, trace-id нет |
| 114 | §13.114 | **PASS** | P-DIR1: пользовательские числа сохраняются, внутренний ключ отделён структурно (без regex по цифрам) |
| 115 | §13.115 | **PASS** | Re-check 2 (`fb761f73`): после рестарта (свежий процесс, свежая SQLite) окно и цепочка несут те же рёбра (8002↳8001, 8004↳8002, 8005↳8003), реальных участников и абсолютные даты; P-DIR1 сохраняет даты, авторов и роли при рёбрах Reply |
| 116 | §13.116 | **PASS** | P-DIR1: роль бота «(бот)» (T test_forward_and_bot_role_are_kept_in_thread) и свои слова в рамке; корректировка не теряется |
| 117 | §13.117 | **PASS** | P-RST: свежий процесс и SQLite — окно, цепочка 8004-8002-8001 и метки восстановлены из БД, прогретых кешей нет |
| 118 | §13.118 | **PASS** | Это ревью: типизированные данные, фактический payload и итог для Direct, FactCheck, RAG, tools и мема; автор, контекст, время и источник на месте, новых LLM-вызовов нет |
| 119 | §13.119 | **NOT PROVEN** | Просьба дать проверенную ссылку или дату: фактическая выдача не наблюдалась |
| 120 | §13.120 | **PASS** | P-DIR1, P-RST и P-MSC на других именах, ID и темах; код без привязки к инциденту (grep) |

Итого после Re-check 1: **PASS 95**, **FAIL 2** (99, 115), **NOT PROVEN 23** (всего 120).

Итого после Re-check 2 (`fb761f73`): **PASS 97**, **FAIL 0**, **NOT PROVEN 23** (всего 120).


## Блокирующие находки

**B1 (BLOCKER, Builder). Недействительная трасса §7/§11.3 — сценарий 26 FAIL.**
`plans/features/evol-reply-context-integrity-01/evidence/trace-factcheck-target.txt` (sha256 `52ce7d3a…`) содержит
`provider_down: provider_attempts=0 provider_failures=2`. В реальном прогоне `provider_attempts` считается по
`provider_status` фактических claim-ов (`services/factcheck_service.py:1273-1285`): ноль попыток при двух отказах
невозможен. Файл воспроизводит разовый `trace_run.py` из `WorkspaceData/runs/rc-factcheck-trace/`, который сам
конструирует `RetrievalOutcome(provider_failures=2)` без claims. Сквозного пути
trigger — target — context — claim — search — verdict — delivery в артефакте нет.
Минимально: снять трассу реальным прогоном (включая реальный отказ провайдера), проверить внутреннюю согласованность
счётчиков, приложить артефакт к карте на этом кандидате. Повторная проверка: та же строка матрицы с
`provider_attempts >= provider_failures` и полным набором стадий.

**B2 (BLOCKER, PM). Строгий гейт приёмки не проходит ни по одному срезу на этом кандидате.**
`requirements_gate.py check --stage review --slice <любой из 8> --candidate bfa26e60 --repo .` даёт
`inventory=312 manual=43 scoped=27..49 errors=29..66`, все строки PENDING; на кандидате `4baccb1d` гейт падает ещё и
на `candidate mismatch`. Строки RC-S001..RC-S120 не имеют привязанного к кандидату доказательства, `review_binding`
описывает только фактчек-срез.
Минимально: после B1 связать строки с `artifact_path` на фактическом кандидате и прогнать `--stage review`.
Повторная проверка: `errors=0` для срезов, входящих в релиз.

## Related-small (в тот же патч)

**B3 (сценарии 99/115). Окно не несёт подтверждённых reply-рёбер.** P-DIR1: сообщение 6106 — реальный Reply на 6103,
но в `<Global_Context>` нет ни `↳ Reply`, ни честной пометки; ребро печатается только для цепочки триггера.
`canonical_context.SpeechRelation` уже умеет reply, semantic и missing_edge, но окно его не использует.
Минимально: для строк окна с `reply_to_id`, разрешимым внутри окна, печатать `↳ Reply M<label>`. Проверка: payload
6106-6103 содержит ребро, ложных рёбер нет.

**B4 (сценарий 111). `reply_chains` исчезает молча при тесном бюджете.**
`services/chat_context.py:254-262`: при `remaining <= 0` возвращается пустая строка, без пометки и без записи в
трассу (в P-MSC при 420/380/300 цепочки нет, пометка только про окно). Функция `_reply_chains_omitted_note` в модуле
уже есть.
Минимально: пометка о вытесненной цепочке плюс счётчик в трассе. Проверка: при бюджете 300-420 в payload есть пометка,
`omitted_chain>0` в логе.

**B5 (сценарий 7). Семантическая связь объявлена в рендере, но не создаётся в проде.**
`SpeechRelation(kind=semantic)` строится только в тестах; `thread_chain.py:528` создаёт лишь `kind=reply`. В payload
семантическая связь никак не помечена (в трассе — `basis=semantic`).
Минимально: создавать отношение semantic там, где suitability или social-frame установил связь без Reply.
Проверка: строка `↳ по теме M2 (не Reply)` в payload для тематически связанной реплики без Reply.

## Открытые пункты, по которым решение принято (не блокируют этот кандидат)

1. **Маршрут suitability-гейта** (`handlers/factcheck.py:353-359`): `ctx.render_feed()` без проекции и без под-блока
   цепочки; P-FC1 показывает `tg:6990..7005` и пустой набор меток. Гейт по умолчанию OFF
   (`factcheck_suitability.suitability_gate_enabled()` возвращает False), поэтому для приёмки этого кандидата это
   допустимо: маршрут не действует, а внутренний фактчек-контекст по §5.1 вправе нести настоящие ID. При включении
   гейта нарушится правило «одна проекция на прогон» и потеряется родитель вне окна — в бэклог: одна проекция и цепочка
   в гейте.
2. **Свободный текст инициативы goal и rationale** (`direct_chat_service.py:12849-12862`): доходит до Writer
   дословно как данные; `rationale` обрезан 200 символами, `goal` — без потолка. Конструктивного пути попадания ID
   туда нет (текст пишет Наблюдатель), поэтому приемлемо; в бэклог — такой же потолок для `goal`.
3. **Бэклог прошлых ревью** (метка медиа дублируется в заголовке и маркере, «изображение msg:0», стохастика S6,
   `bot_id=None` fail-open, числовой fallback имени при пустом алиас-каскаде) остаётся без расширения текущего скоупа.
   Отдельно: строки окна не печатают `quote_text` вообще (только строки цепочки) — предсуществующее ограничение,
   в P-RST сообщение M6 с цитатой показано без цитаты.

## Что осталось непроверенным (не дефекты, а отсутствие доказательств)

Сценарии 25 (два чата параллельно), 27 (окно в сотни сообщений), 34/36/37/41 (реальный Vision/OCR и media-pending через
рестарт), 42 (инструментальный медиа-маршрут), 47 (реальный сбой извлечения при привязанной ссылке, открытый N2),
50/51 (живой текст вердикта и совместный рендер чанков), 63/87/119 (технический вопрос, авторизованная диагностика,
запрос ссылки или даты), 89/90 (кросс-тёрн после исправления, отсутствие «долговременного урока»), 102/107 (связь через
50-100 сообщений, чужой чат в памяти), 21/22 (память про отсылку), 18 (voice/транскрипция, форвард без даты),
112 (сборка саммари), 7/111 (см. B4/B5). Сценарии 99/115 закрыты в Re-check 2.

Это не разрешение выпускать: обязательные сценарии без доказательства остаются UNVERIFIED, итоговый DONE по пакету
не выдаётся.

## Следующее действие

1. Builder: B1 (перегенерировать трассу реальным прогоном), B3, B4, B5 — одним узким патчем и по одному тесту.
2. PM: после B1 связать RC-S001..RC-S120 и строки срезов с артефактами на фактическом кандидате, прогнать
   `--stage review` до `errors=0`.
3. Reviewer (повторно): мои пробы P-DIR1 (ребро 6106-6103), P-MSC (бюджет 300-420, пометка цепочки), payload с
   `↳ по теме … (не Reply)`, перегенерация трассы плюс целевые наборы тестов. Остальные доказанные строки не
   переснимать.


## Re-check 1 — кандидат `ff13141d`

- Кандидат: ветка `rc/accept-fixes` @ `ff13141d`, база `4baccb1d`;
  worktree `WorkspaceData/worktrees/c742e4de9e92c489/evol-rc-accept-fixes-f374fedfbc58-bcc50969`.
- Диф: 8 файлов (`services/chat_context.py`, `services/direct_chat_service.py`,
  `services/factcheck_context.py`, `services/factcheck_orchestrator.py`, `services/factcheck_suitability.py`,
  `scripts/evol_trace_factcheck_target.py`, `tests/test_evol_rc_accept_fixes.py`,
  `plans/features/evol-reply-context-integrity-01/evidence/trace-factcheck-target.txt`).
  `web/**` и тексты промптов не тронуты.

### Вердикт: **Needs Fixes**

B1, B4, B5 закрыты и подтверждены моими прогонами.
B3 не работает на реальных данных (ребро не печатается) и в редком случае может дать
**ложное** ребро → сценарии 99/115 остаются FAIL, релиз заблокирован.

### Три линии доказательств (этот кандидат)

- **Implementation.** Прочитаны изменённые пути: рендер окна и усечение
  (`chat_context.format_chat_context`, `_notes_reserve`/трёхпроходный резерв, `_reply_chain_steps`),
  строка `<Global_Context>` (`direct_chat_service._context_row_line` и карта `window_items`,
  `reply_parent_row_id`), фид фактчека (`factcheck_context.render_feed`, `_render_line`),
  семантическая связь (`factcheck_suitability._semantic_link`), оркестратор
  (`factcheck_orchestrator._run_inner`:932-934), шов `canonical_context.SpeechRelation/format_speech_item`.
- **Test validity.** Прочитаны тела и утверждения 11 новых тестов: B4/B5 проверяют
  фактический текст и счётчики, но тесты B3 закрепляют **неверное предположение**
  (`reply_to_id` = `id` строки БД), а `test_global_context_row_marks_reply_edge` вообще подаёт готовую
  карту `window_items` вручную, минуя реальную сборку. Зелёный набор здесь
  не доказывает требуемого поведения.
- **Independent challenge.** Мои прогоны в `WorkspaceData/runs/c742e4de9e92c489/evol-rc-accept-recheck1-fb3047dbb9de/`:
  трасса дважды снята и сверена по sha256; ребро в окне на реальном формате строк;
  тесные бюджеты 700/420/380/300/220; семантика vs structural vs tiebreak;
  повтор прежних проб P-DIR1/P-DIR2/P-FC1/P-RST/P-MSC.

#### B1 (Закрыто)
- Скрипт `scripts/evol_trace_factcheck_target.py` в репозитории. Два моих прогона (`--write`) и файл в репозитории
  дают один sha256 `24b67a2597e75a0c1566122a51de4d16e4bfb34fc976c6248cbc426ed70fc588`
  (5376 символов): артефакт не правился руками.
- Счётчики согласованы и выведены из фактических объектов: `provider_attempts` = число
  реальных вызовов агрегатора (мой instrumented-прогон: provider_down 2/2, deadline 0/0,
  empty_results 2/2, no_relevant 2/2, no_citable 2/2, extract_failed 2/2), `attempts >= failures`, нет документов без
  результатов, `extract_attempts = failures + successes`.
- Все стадии trigger → target → context → claim → search → verdict → delivery есть (1/7..7/7); честно
  названо неисполненное (LLM, сеть, сетевая отправка); правило доставки
  соответствует `handlers/factcheck.py:1105-1107`.

#### B3 (НЕ ЗАКРЫТО — blocker, Builder)
- Новый код считает `smart_messages.reply_to_id` идентификатором строки БД и ищет
  родителя в `window_items` по `row["id"]`. В проде туда пишется **Telegram message_id**:
  `handlers/summary.py:476-478` (`message.reply_to_message.message_id`), `handlers/youtube.py:963-965`;
  так же читают `direct_chat_service._correction_reference_kind` (by_tg_id),
  `factcheck_suitability._infer_source_claim`, `canonical_messages`, `direct_context_composer`.
- Фактическая БД (`local_database_2026-09-04_history.db`, read-only): 12/12 ребер разрешаются
  по `tg_message_id`, 0/12 по `id`.
- Прогон через реальный `_build_user_content` с прод-форматом строк (6106 reply_to_id=6103):
  строка `<Global_Context>` — `<ARROW>` **нет**. Тот #6е результат в `format_chat_context` (`↳ Reply` нет).
- Ложное ребро: если в окне есть строка с `id`, равным
  `reply_to_id` родителя (телеграмный id), ребро указывает на совершенно
  чужое сообщение (проверено: `↳ Reply M1` на «совсем другая тема»).
- Минимально: разрешать родителя по `tg_message_id` внутри того же набора
  строк (как уже делает `_correction_reference_kind`), оба места (chat_context + Direct); тесты строить
  от реального пути сборки и прод-формата строк.

#### B4 (Закрыто)
- 700: цепочка в блоке; 420/380/300: «…цепочка ответов не показана (2)» — точное N,
  в логе `omitted_chain=2 | omitted_chain_steps=2 | budget=...`; длина блока 398/329/260 ≤ бюджета;
  потолок `_REPLY_CHAINS_MAX_CHARS=1200` не изменён. 220 — пустой блок (прежнее поведение).

#### B5 (Закрыто, с одним related-small)
- Тематический антецедент (basis=topic): «↳ по теме M3 (не Reply)» в фактическом фиде
  (трасса-скрипт + мой прогон через `_semantic_link`+рендер); structural и tiebreak не помечаются.
- Related-small (Builder): на маршруте `factcheck_orchestrator._run_inner` новый фид с метками не
  эмитит `speech_projection` → метки без обратной карты в трассе (§9.4/сц.109): добавить
  `emit_speech_projection_event(projection, chat_id=..., run_id=...)` рядом с `render_feed`.

#### Регрессии
- 11 новых тестов зелёные; 164 теста consumers/seam/target-media/self-correction и 135
  тестов epic65/factcheck-context/target-marking/native-reply — без падений.
- Прежние пробы воспроизведены: отличия только в идентификаторах
  MagicMock и в тесном бюджете (420: 369→402 — добавилась пометка цепочки, в бюджете).
  Промпты и `web/**` не менялись.

### Следующее действие
1. Builder: ребро Reply в окне — разрешать по `tg_message_id` (оба места), тесты через
   реальный путь сборки; + related-small событие проекции в оркестраторе.
2. PM: привязка карты к новому кандидату (сейчас `candidate_commit = bfa26e60`).
3. Reviewer: повторно сц. 99/115 на реальном формате строк + отсутствие ложных рёбер.

## Re-check 2 — кандидат `fb761f73`

- Кандидат: ветка `rc/accept-fixes` @ `fb761f73`, база `4baccb1d`, предыдущий кандидат ревью `ff13141d`.
- Диф к `ff13141d`: 5 файлов — `services/chat_context.py`, `services/direct_chat_service.py`,
  `services/factcheck_orchestrator.py`, `services/factcheck_suitability.py`,
  `tests/test_evol_rc_accept_fixes.py`. `git diff --name-only ff13141d fb761f73 -- web/**` пуст, промпт-тексты
  и конфигурация не менялись (в добавленных строках нет Personality/Style/prompt строк).

### Вердикт: **Approved** (узкий срез B3 + трасса; не DONE по пакету)

Сценарии 99 и 115 закрыты на реальных данных, related-small к B5 (обратная карта на маршруте оркестратора)
закрыт. Родительский `DONE` этим вердиктом не выдаётся: B2 (привязка карты к кандидату и строгий гейт) остаётся
за PM, 23 сценария остаются NOT PROVEN.

### Три линии доказательств (этот кандидат)

- **Implementation.** Прочитаны изменённые пути целиком: разрешение родителя (`chat_context._reply_parent_tg_message_id`,
  `_row_tg_message_id`, карта `window_refs`; `direct_chat_service.reply_parent_tg_message_id`, `window_refs_by_tg`,
  `_context_row_line(window_items=...)`), обе сборки `<Global_Context>` (`_build_global_context_parts` — хвост
  и композерный `_compose_middle_lines`, `_build_global_context` — legacy-путь), эмиссия трассы
  (`factcheck_orchestrator._run_inner`, `factcheck_suitability.resolve_context_claim`). Запись `reply_to_id`
  сверена с прод-писателем: `handlers/summary.py:476-478` (`reply_to_message.message_id`), `handlers/youtube.py:963-965`;
  читатели, подтверждающие ту же семантику: `canonical_messages.py:137,198-199`, `factcheck_context.py:537`,
  `factcheck_service.py:942,1082`.
- **Test validity.** Прочитаны тела 15 тестов `tests/test_evol_rc_accept_fixes.py`. Тесты B3 действительно
  различают старое и новое поведение: декой-строка получает `db_id=TG_ROOT` и проверяется утверждением
  `"↳ Reply {decoy}" not in block`, то есть при возврате старой семантики тест падает. Слабое место:
  тест оркестратора проверяет только две метки фида, а не полноту обратной карты — полноту я проверил отдельно.
- **Independent challenge.** Свои строки и своя БД: реальный `DatabaseService.initialize()` (штатная схема),
  вставка штатным писателем `save_smart_message(..., message_id=)` (прод-формат: `id` строки БД — 601..609,
  telegram id — 6101..6109), чтение окна штатным `db.get_messages_around`, рендер штатными
  `chat_context.build_chat_context` и `DirectChatService._build_user_content` (композер ON и OFF), плюс тот же
  набор строк на коде `ff13141d` в отдельном ворктри для сравнения.

### Наблюдённые рёбра (мои данные, не Builder-овы)

Окно: `601/6101/—`, `602/6102/—`, `603/6103/—`, `604/6104/reply_to_id=6101`,
`605/6105/—`, `606/6106/reply_to_id=603` (декой: 603 — это `id` строки сообщения 6103),
`607/6107/reply_to_id=999999`, `608/6108/reply_to_id=6103`, `609/6109/—` (триггер).

| Потребитель | M4 (реальный Reply на M1) | M8 (реальный Reply на M3) | M6 декой (`reply_to_id` = чужой `id`) | M7 (родитель вне окна) | M5 (сосед по теме) |
| --- | --- | --- | --- | --- | --- |
| `format_chat_context` | `↳ Reply M1` | `↳ Reply M3` | ребра нет | ребра нет | ребра нет |
| `<Global_Context>` композер ON | `↳ Reply M1` | `↳ Reply M3` | ребра нет | ребра нет | ребра нет |
| `<Global_Context>` композер OFF | `↳ Reply M1` | `↳ Reply M3` | ребра нет | ребра нет | ребра нет |
| тот же набор на `ff13141d` | ребра нет | ребра нет | **ложное** `↳ Reply M3` (в chat_context и в композер-OFF) | ребра нет | ребра нет |

То есть регресс закрыт с обеих сторон: настоящее ребро печатается, ложное — нет, `tg:`-метки в payload не
просачиваются (`raw_tg_leak=False`), `↳ Reply` не выдумывается для соседства.

Отдельно проверено: родитель с пустым текстом (медиа), который в окно виден, но не рендерится. При включённом
медиа-гейте ребро ведёт на маркер (`↳ Reply M1`), при выключенном — честная фраза
"↳ родитель вне доступного окна (связь известна)"; висячих меток нет (`UNMAPPED=[]`).

### Трасса (§9.4 / сц.109)

- probe-маршрут `factcheck_suitability.resolve_context_claim` и оркестратор `factcheck_orchestrator._run_inner`:
  ровно одно событие `speech_projection` на прогон, корреляция `chat_id` + `message_id` (цель) + `run_id`
  (`factcheck:-1007710001:8803`).
- Полнота: все метки, реально попавшие в фид (M1, M2, M3, U1, U2, U3), есть в `items`/`participants` —
  `MISSING=[]` на обоих маршрутах. Тест Builder-а проверяет только две метки; здесь проверено полное покрытие.
- Фид при этом помечает смысловую связь явно: `↳ по теме M3 (не Reply)` (B5 не сломан).

### B1 (артефакт трассы)

`sha256 24b67a2597e75a0c1566122a51de4d16e4bfb34fc976c6248cbc426ed70fc588`, 6172 байта. Прогон
`scripts/evol_trace_factcheck_target.py` на `fb761f73` воспроизводит файл **байт-в-байт**; в этом коммите
скрипт и артефакт не менялись.

### Регрессии и повтор прежних проб

- 179 тестов (`test_evol_rc_accept_fixes`, `test_evol_reply_context_consumers`,
  `test_evol_reply_context_integrity_seam`, `test_rc_direct_self_correction`, `test_rc_target_media_evidence`) —
  зелёные. 390 тестов `test_factcheck_*` — зелёные.
- Direct-профиль: 423 пройдено, 5 падений — все в `tests/test_direct_fallback_recompose_asap32.py` и все
  падают идентично на `ff13141d` (`fb_retries(sent=...)` в `services/llm_client.py`). К этому коммиту отношения
  не имеют, предсуществующие.
- P-DIR1: ребро 6106↳6103 теперь есть и в `<Conversation_Branch>`, и в `<Global_Context>`; `ref_leak=[]`,
  `uid_leak=[]`, `other_chat_leak=False`, обратная карта полная (M1..M8, U1..U5), две тёзки различаются
  (`Ирина (U2)` против `Ирина (#8003) (U3)`), forward сохранён.
- P-DIR2: цитата без Reply — во всех трёх режимах одинаково, выдуманного Reply нет, автор цитаты честно
  "не определён".
- P-FC1: фид по умолчанию с метками и `↳ Reply M2` в цепочке, `raw_refs=[]`.
- P-RST: свежий процесс и свежая SQLite — рёбра 8002↳8001, 8004↳8002, 8005↳8003
  восстановлены из БД, цепочка 8004↳8002↳8001, обратная карта полная.
- P-MSC: бюджеты 700/420/380/300/220 без изменений, пометки о вытеснении на месте, RAG старый/новый,
  инструменты, мем (M15/M16), лор — как в Re-check 1.
- Откат: при рубильнике речи OFF вывод `format_chat_context` **байт-идентичен** старому коду
  (sha256 `68231638360905e3967e147372452da9f96cde2fb0a767f1e6ac90428d1321a2` на обоих кандидатах).

### Неблокирующие наблюдения (бэклог)

1. При **активном бегущем конспекте** композер режет окно на middle и tail и строит для них РАЗНЫЕ карты рёбер:
   хвост получает `tail_refs` только из `tail_rows`, middle — из выбранных строк. Ребёнок в хвосте с
   родителем в middle ребра не получит, хотя оба видимы. Это чтение кода, а не наблюдение: ветку с конспектом
   включить не удалось (гейт `flags.chat_running_summary_enabled` в моей фикстуре не сработал). На буквальный
   сценарий 99 ("рядом") не влияет, ложных утверждений не даёт.
2. Фикстура трассы (`scripts/evol_trace_factcheck_target.py`, `_row(..., reply_to_db=...)`) кладёт в `reply_to_id`
   `id` строки (`TARGET_TG+100`), а не Telegram id — модель данных в фикстуре не соответствует подтверждённой
   прод-семантике. На собственные утверждения трассы не влияет (цель объявлена явно), но при следующем касании
   фикстуру стоит привести к прод-формату.
3. Устаревший docstring `tests/test_evol_reply_context_consumers.py::_row`: "reply_to_db — id строки-родителя".
4. Эпизодные строки (`_build_old_episodes`) и middle-строки рендерятся без карты окна — рёбер там нет;
   не регресс, но и не покрыто.

### Следующее действие

1. PM: B2 — связать карту с `fb761f73` (сейчас `candidate_commit = bfa26e60`) и прогнать
   `--stage review` по срезам; на моём прогоне гейт даёт `candidate mismatch` и PENDING по всем срезам.
2. После привязки — обычный релиз по правилу PET_PROJECT; код к релизу готов.