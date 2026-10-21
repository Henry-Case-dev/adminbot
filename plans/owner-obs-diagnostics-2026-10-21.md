# Диагностика наблюдений владельца — 21.10.2026 (read-only)

Метод: только чтение. Прод **2.58.105 @ a6246e33** (healthz подтверждает 2.58.105, сервис active, рестарт 08:32 UTC 21.10). Источники: PG `bot_settings`/`chat_profiles`/`llm_usage_events` (SELECT), SQLite `local_database.db` (read-only URI: `mca_events`, `nostalgia_log`, `mca_bot_outputs`, `smart_messages`, `task_jobs`), journalctl `admin_bot` (48ч/7д), код HEAD a6246e33. Прод не изменён: 0 конфигов, 0 БД-записей, 0 сообщений в чаты. SSH: 3 коннекта суммарно (recon + 2 пачки read).

Чаты: старый `-1002661910336`, новый `-1004482340693`, личный владельца `5885953495`. Все LLM-вызовы за 48ч — одна модель `deepseek/deepseek-v4.1-flash` (fallback на другие модели не наблюдался; 7д: 2446 вызовов flash + 34 `deepseek-flash` + 114 без модели = image-модуль).

---

## 1. EXPRESSION: почему EPISODIC/FREQUENT почти не дают мата

**Факты (подтверждено):**
- Effective-конфиг правильный: чат `-1002661910336` — per-chat override `character.expression = {profanity: "frequent", wit: high, sharpness: sharp, revision: 2, updated 2026-10-20T15:20:41Z}` (PG `chat_profiles.chat_params.overrides`). Глобально `bot_settings.character.expression.profanity = "allowed"` — это read-alias старого формата → `occasional` (`services/mca_expression.py:36`). Чат `-1004482340693` без override → occasional.
- Слой доезжает до боевой сборки, «preview-only» гипотеза (ADD-EXP §3.2, ранний вердикт) **не подтверждается**: боевой wiring L2 Writer — `services/direct_chat_service.py:4485-4506`; авторские жанры (ностальгия и др.) — `services/mca_authorial_speech.py:120-130`; вне-композерные речевые маршруты — `services/prompt_composer.py:740-782` (speech_owner_block). За 48ч событий `policy_not_injected` / `composer_excluded` — **0** (grep journal3), в `prompt_layers` только ожидаемое `expression:profile:machine_stage` (L1-машинная стадия, слой туда не положен по дизайну).
- Конфликтов инструкций не найдено: PG-канон Direct writer (`prompts.direct_chat_system_prompt`, от 07.10) содержит «Разрешен мат и сленг» — не противоречит; `public_speech_guard` чистит только «закулисный метатекст»/машинные артефакты (`services/public_speech_guard.py:596+`), мат не трогает; `style_policy` — типографика (кавычки/эмодзи/переносы), не лексика. Fallback-репак L2 сохраняет system целиком (expression внутри) — `services/direct_execution.py: build_l2_fallback_adapter`.
- Few-shot `<Expression_Examples>` НЕ едет: `prompt_layers` = `few_shot:not_owner_approved` (и `samples_absent`) — ни один заводской пример мат-регистра не одобрен владельцем (`owner_approved=1` требуется, `services/mca_expression.py:397-443`). Это не блокиратор политики (она едет отдельным слоем), но усилителя тоже нет.
- **Прямые диагностические события на проде** (`mca_events.event_name=expression_diag`, обе — WARN):
  - `2026-10-20 05:14:52 UTC` — класс `model_ignored_instruction`, mode=frequent, detail `frequent_no_mat_n9` (9 проб подряд без мата, accept96 live-set);
  - `2026-10-20 08:24:10 UTC` — `model_ignored_instruction`, mode=frequent, detail `f4_matrix_n5` (5 проб, accept97).
  Класс ставится контролируемыми пробами только при marker_present (слой в payload подтверждён) и после ≥5 повторов (`services/mca_expression.py:505-526`).

**Вероятная причина (подтверждена пробами):** политика frequent реально в payload, модель `deepseek-v4.1-flash` инструкцию игнорирует (RLHF-safety). Это не отсутствие слоя, не «preview-only» и не постобработка.

**Уже сделано ранее:** директивы occasional/frequent переписаны на короткие прямые тексты владельца (ADD-SAMPLES-UX §2, 20.10, `services/mca_expression.py:71-85`); «preview-only» исправлено в 2.58.98.

**Что реально менять (без реализации):**
1. Ключевой рычаг — модель слота писателя (каталог `models.*`): проверить flash на инструкции про мат в harness и при необходимости поднять класс/сменить провайдера для Direct writer.
2. Одобрить владельцем заводские примеры мат-регистра (вкл. few-shot `<Expression_Examples>`).
3. Опционально: поднять позицию/вес слоя Expression в финальном system (осторожно, без нового постпроцессора — EXP-INSTR.NOPOST).

---

## 2. DIRECT: текстовый ответ на бессмысленные продолжения («лол»)

**Факты:**
- Тумблеры: `flags.chat_decision_ignore_trivial_enabled=true`, `reactions=true`, `image_reactions=true`, `flags.chat_silent_ack_enabled=true` (глобально и per-chat у старого чата), `flags.chat_autonomous_reply_enabled=true`. Путь reply_to_bot — автономный, всё разрешено.
- Детерминированная матрица работает: в журнале многократно `DECISION_COMPLETE action=silent reason=recent_reply trigger_type=reply_to_bot message_class=other` (например 20.10 07:59:52, 20.10 20:00:07, 21.10 07:03:13) — система recognizes тривиальные продолжения.
- Но при включённом L1 Planner (на проде ON: 43 `L1_PLAN` за 48ч) старый silent-шорткат отключён **по коду**: условие `pre_action == ACTION_SILENT and not decision_llm_pending and not direct_l1_on` (`services/direct_chat_service.py:2580-2601`). В L1-режиме решение отдано LLM-планеру; silent допустим (`ACTIONS = ("reply","react","silent")`, `services/direct_l1.py:41`; путь l1_silent→🗿 реализован, `direct_chat_service.py:2887-2917`).
- **Факт за 48ч: 43/43 `L1_PLAN action=reply`, 0 react, 0 silent; `MESSAGE_IGNORED` (l1_silent) — 0 событий.** PG-промпт планера (`prompts.direct_l1_planner_system_prompt`, от 16.10) silent/react упоминает — модель deepseek-flash фактически всегда выбирает reply.
- Итог 48ч: direct_reply отправок — 142 (старый чат) / 20 (новый); каждое «silent»-решение матрицы превращалось в текст (DIRECT_FRESH_GENERATION 137 у старого).
- Force-путь (бот-слово/имя/@mention) — `reason=force_direct` → REPLY всегда по дизайну (гейт до Decision), это не дефект.

**Вероятная причина (подтверждена):** поведенческий разрыв — матрица признаёт сообщение тривиальным (silent), но в L1-режиме это решение лишь demote-fallback; LLM-планер на flash-модели никогда не выбирает silent/react, поэтому «лол»-класс получает текст.

**Что реально менять (варианты, без реализации):**
1. Детерминированный guard поверх L1: `pre_action=silent ∧ message_class=other/laughter ∧ reply_to_bot ∧ confidence < порога` → демотировать reply в silent/🗿 (использовать уже существующий `_execute_silent_ack`).
2. Либо усилить ПРАВИЛА L1-промпта (PG-ключ) примерами «пустая реплика на ответ бота → silent/react».
3. Либо per-chat тумблер «строгого молчания» (новый каталог-ключ) — продуктовое решение владельца.

---

## 3. NOSTALGIA: источник, достоверность, «ложные факты» и «нерелевантные годовщины»

**Факты:**
- Источник кандидатов — только реальные данные чата: year_back = `smart_messages` этого же чата в окне «ровно год назад ±2 дня» (`memory.nostalgia_year_back_days_window=2`, ≤3 строки, `services/nostalgia_worker.py:734-747`); golden = факты памяти с importance ≥ 5 и возрастом ≥ 60 дней. В user-блок LLM строки едут с именем и датой; жанровый канон запрещает выдумывать события/участников.
- DB-сверка 4 из 4 отправленных за 18–21.10 кандидатов — **все реальные сообщения, байт-в-байт, авторы — реальные участники чата** (`smart_messages`):
  - «у знакомого стоматолога, который маму лечил тыщу лет» — id 487463, Мистер Служба, 2025-10-21 ✓ (отправлено 21.10 07:00 UTC);
  - «Мне кажется я никогда не буду счастливее чем летом 2024» — id 485931, Олеяка, 2025-10-20 ✓ (отправлено 20.10 05:42);
  - «ауру вижу» — id 485777, рин118, 2025-10-19 ✓ (отправлено 19.10 15:54);
  - «>олеся говноед» — id 487169, сглыпа), 2025-10-20 ✓ (отправлено 20.10 18:03).
  Ложных участников/событий на уровне кандидатов нет.
- «Нерелевантные годовщины» — подтверждено как свойство порога: threshold = 0.3 + aggressiveness(0.3)×0.5 = **0.45**, вес year_back фиксирован **0.7** → любое сообщение годичной давности проходит всегда (`services/nostalgia_worker.py:701-732`). Отсюда воспоминания из односложных реплик («ауру вижу»). Селективность механизмом не предусмотрена; LLM имеет право UNCHANGED и иногда им пользуется (2ch-видео 20.10 04:41 — skipped unchanged).
- Финальный текст (что LLM дописал поверх кандидата) хранится в `mca_bot_outputs.content_text`; точную построчную сверку финальных текстов в этой сессии не завершил (запрос с неверным именем колонки; SSH-бюджет исчерпан). Если владелец видел выдуманные детали — это LLM-добавка поверх реального кандидата (пример нужен — см. owner_live_checks §9).

**Уже сделано ранее:** инициатива ностальгии идёт через единый Decision/транспорт (`path: "initiative"` во всех sent); P0-followup: преамбула «живая беседа» (scenario=A) вместо ложного «давно тихо» — в журнале подтверждено (21.10 05:00 «silence=2min → гейты тишины не применяются»).

**Что реально менять (без реализации):**
1. Селективность year_back: поднять порог только для year_back (например требовать min длину/вес строки-кандидата) ИЛИ уменьшить окно/частоту — конфиг-правка владельца (`memory.nostalgia_aggressiveness`, `year_back_days_window`).
2. Завершить сверку финальных текстов с кандидатами (SELECT `mca_bot_outputs` — следующий read-проход, без владельца).

---

## 4. INITIATIVE REPLY: путь addressee_user_id → Telegram delivery

**Факты (код HEAD a6246e33):**
- Адресат и основания НЕ теряются по пути в Writer: `build_opportunity_row` кладёт `addressee_user_id` + `rationale` + `source_refs` (msg:ID списком до 4) — `services/initiative_observer.py:822-860`; строка доезжает до L1/Writer как контекст повода (`direct_chat_service.py:9202 _ephemeral_intent_row`, `plan_initiative_decision`).
- Связка теряется ровно в одной точке — отправка: `direct_chat_service.py:9363-9367` `message = await _tg_send.send_text(bot, chat_id, chunk)` — **без `reply_to_message_id`**. Все 24 initiative-отправки за 7д (14 старый чат + 10 новый) — standalone (журнал 18.10–21.10), совпадает с кодом.
- Объём недостающего — небольшой:
  1) резолвер «адресат → сообщение»: `source_refs` (msg:<smart_messages.id>) → колонка `smart_messages.tg_message_id`, либо fallback — последний `tg_message_id` пользователя `addressee_user_id` в чате; таблиц/миграций не нужно (данные уже есть);
  2) передача `reply_to_message_id=...` в цикле чанков — `send_text` уже принимает `**kwargs` (`services/telegram_send.py:105-107`), менять сигнатуру не надо; по прецеденту `smartmodule_utils.py:8` reply вешается только на первый чанк;
  3) защитное условие: цель протухла (старше N часов / `reply_to_message_id` > текущего) → отправить без reply (паттерн `_is_reply_target_gone` уже есть в `smartmodule_utils`).
  Ностальгия/heartbeat идут через тот же `handle_initiative` без адресата — для них reply не ставится (только при наличии `addressee_user_id`/`source_refs`).

**Вероятная причина отсутствия реализации:** фича адресата доведена до генерации (Writer знает, к кому обращаться), но транспортный хвост (reply-привязка) не был в срезе.

---

## 5. INITIATIVE TWO CHATS: сравнение за одинаковые последние 48ч

**Факты (окно 19.10 ~10:20 → 21.10 ~10:20 UTC, одинаковые гейты):**

| метрика | старый -1002661910336 | новый -1004482340693 |
|---|---|---|
| сообщений (smart_messages) | 2515 | 576 |
| initiative_opportunity success / skipped | 14 / 8 | 10 / 5 |
| decided: reply / silent(l1_silent) / прочее | 10 / 7 (+1 l1_unavailable) | 7 / 1 (+1 cancelled recheck_deferred) |
| отправок initiative_reply (journal = mca_bot_outputs) | **10** | **7** |
| nostalgia | 4 sent за 48ч (год назад) | **всегда no_candidates** |

- Per-chat overrides `initiative.*` нет ни у одного чата; профиль global `normal`: min_gap 7200с, max/day 6, max/topic 1, eval_min_messages 8, eval_interval 2700с, eval_llm_budget 12/день — гейты идентичны.
- Cursor не лагает: курсор наблюдателя 2355443 vs max(id) 2355444 (лаг ≈1 строка). Счётчики наблюдателя (lifetime payload): evals 58, opportunities 35, silent_decisions 15, sent 18, react 0.
- Отличие в skip-профиле: у старого чата чаще `l1_silent` (7 против 1) — L1-планер на инициативных ходах чаще решает молчать (чаше шумный контекст); у нового чаще `recheck_deferred` (1 случай 21.10 08:01 — контекст сменился, перенос).
- **Вероятная причина ощущения «новый чат получает меньше инициативы»:** new_message-инициативы в новом чате работают даже плотнее (7 отправок на 576 сообщений против 10 на 2515). Реальная структурная асимметрия — **ностальгия**: чат создан 14.10.2026, year_back не имеет истории годичной давности, golden требует фактов старше 60 дней → `no_candidates` каждый час (журнал, `nostalgia_log` 30+ строк skipped). Это не дефект алгоритма, а следствие возраста чата; алгоритм не менял.

---

## Сводка

| # | Вопрос | Вердикт |
|---|---|---|
| 1 | EXPRESSION | Подтверждено: слой frequent в payload, модель deepseek-flash игнорирует инструкцию (прод-пробы n9/n5 `model_ignored_instruction`). Не «preview-only». |
| 2 | DIRECT | Подтверждено: матрица молчит (silent/recent_reply), но в L1-режиме LLM-планер 43/43 выбирает reply → текст на «лол». |
| 3 | NOSTALGIA | Кандидаты достоверны (4/4 сверены с БД); «нерелевантность» = низкий порог (0.7 ≥ 0.45 всегда); финальные тексты LLM — сверка не завершена. |
| 4 | INITIATIVE REPLY | Подтверждено: теряется только на отправке (`send_text` без reply_to); недостающий объём — 1 точка вызова + маленький резолвер, миграций нет. |
| 5 | INITIATIVE TWO CHATS | Дисбаланса в инициативе нет (10 vs 7 отправок за 48ч); реальная асимметрия — ностальгия, структурно невозможная в чате возрастом 7 дней. |

Пункты, требующие владельца — см. `plans/owner_live_checks.md` §9.

### Ограничения этой диагностики
- Финальные тексты ностальгии не сверены построчно (ошибка в имени колонки `mca_bot_outputs.output_id`; SSH-лимит исчерпан) — следующий read-проход закроет без владельца.
- Payload LLM не персистится (манифесты in-memory) — «что получил модель» подтверждается косвенно: маркер-диагностика (0 промахов за 48ч) + пробы harness + отсутствие skip-событий слоя.
