# ADD-EXP Ф0 — прод-диагностика «почему мата нет» (read-only + один контролируемый ход)

Лейн **ADD-EXP-F0**. Прод: **2.58.94 @ `9072347b986b91f05d580a11c1aae6646b250e29`**
(MainPID 3657672, NRestarts=0, healthz `ok/2.58.94`), окно **2026-10-19 09:59–10:08 UTC**.
Метод: 1 основной SSH-коннект (read-only пробы + один контролируемый Direct-ход
через harness ACCEPTANCE-91…94, реальная Telegram-доставка локальной Bot API-сессией,
реальные PG/SQLite/провайдеры) + 1 короткая read-only доборка. Настроек/кода не
меняли; тестовое сообщение удалено (правило владельца).

---

## 1. Документ `character.expression` на проде (PG)

| Факт | Значение | Источник |
|---|---|---|
| global `character.expression` | **есть**; `revision=1`; `updated_at=2026-10-18T14:37:25Z` | `probe-after.json` → `bot_settings` |
| значения | `wit=inherit, sharpness=sharp, profanity=allowed, verbosity=inherit, enabled=true, note="", history=[]` | там же |
| override чата `-1002661910336` | **нет** (`chat_params.overrides` — 25 ключей, `character.expression` среди них отсутствует) | `probe-after.json` → `chat_profile.override_keys` |
| effective-источник | **global** (наследование) | API `GET /api/speech/expression` (chat): `present=true, global_present=true, chat_present=false, inheritance=global` |
| rendered-текст (353 симв.) | `<Expression_Settings>… - Резкость: Резче и прямее… - Мат: Мат допустим как естественная часть речи, а не как обязательный элемент каждого ответа. </Expression_Settings>` | `f0-live.json` → `expression_api_chat.body.rendered_text` |
| честный флаг | **`runtime_wired=false`** (оба scope) | там же |
| контекст | `character.core` есть (revision 5, owner_edit, 18.10 14:03Z); gates: `flags.unified_composer_enabled=true` и live `resolve_gates(chat)` → все оси ON, `composer_enabled_now=true` | `probe-after.json`, `f0-live.json.gates_chat` |

## 2. Живой payload-трейс (один контролируемый ход)

Ход: «бот, как настроение?» (синтетический пользователь 990002001, синтетический mid
990940201, chat −1002661910336) → **status=ok, 11.32 c**, ответ доставлен:
mid **1166228**, текст «Нормально, понедельник как понедельник - а у тебя?»
(50 симв., мата нет). correlation_id хода `708f73c41eb64c67b1143184b21a9ab6`;
фактические LLM-вызовы — cid `c448d16a8326`.

Захвачено на границе LLM-клиента (`f0-live.json` → `llm_calls`, `wire_calls`):

| # | module/step | sys chars | sys sha12 | wire payload sha12 | модель |
|---|---|---|---|---|---|
| 1 | (служебный) | 307 | eb60769a4d16 | 96d48fc8a698 | deepseek/deepseek-v4.1-flash |
| 2 | direct_chat / **l1_planner** | 2423 | 99a207313889 | d991666cde3c | — « — |
| 3 | direct_chat / **l2_writer** | 6226 | **0891f2c03128** | **03da7977a131** (20643 симв.) | — « — |
| 4 | (служебный) | 984 | 01be6c765713 | a25b61468f19 | — « — |

- **`Expression_Settings` в payload = 0 вхождений** (`payload_marker_totals`) — ни в
  одном вызове; настройки владельца (`Мат: допустим`, `Резкость: резче`) до LLM не дошли.
- Единственные profanity-упоминания в финальном payload (l2_writer):
  1) канон канала/типографики: «…Разрешен мат и сленг…»;
  2) Core владельца (полный текст, блок **«Мат и грубость.»**: «Мат - естественная
     часть речи… Используй его свободно, если он делает фразу выразительнее…»).
  То есть в payload есть **мягкие разрешения**, но **нет инструкции частоты** и нет
  слоя Expression.
- Состав финального system (6226 симв.): канон вербализатора (СИСТЕМНАЯ РОЛЬ/ПРАВИЛА/
  АНТИ-БОТ/АСИММЕТРИЯ/ТИПОГРАФИКА) → Core владельца → `<Persona>` (правила характера) →
  `<Character_Rules>` → `ОЖИДАЕМАЯ ПОЛНОТА: МИКРО` → `<Style_Policy_Hint>`.
- User-часть содержит план (`emotional_reply/warm`), карту имён и окно чата; мат
  участников в контексте есть (16 hard-совпадений) — это контекст, не инструкция.
- Манифест композера (трасса слоёв) — из событий самого хода (in-process) и durable
  `mca_events`: **`expression:expression_absent` (`reason_code=source_missing`)** для
  chat −1002661910336 (ts 09:59:59Z, `mca_events.id=72922`); пропущены также
  `context_lessons:{style_requests_absent,lessons_absent,speech_absent}`,
  `humor_craft:humor_no_strategy`, `few_shot:samples_absent`,
  `channel_output:channel_output_not_required`,
  `self_model_traits:self_model_folded_into_identity`. Ревизия слоя — не применима
  (слой пропущен до рендера).
- **Реальный прод-процесс (journald, тот же день):** `expression:expression_absent`
  для рабочего чата в 04:55:15Z (PID 3548159, эпоха 2.58.92) и 07:57:28Z (PID 3635488,
  2.58.93); под текущим PID 3657672 событие для рабочего чата ещё не эмитилось
  (дедуп 1×процесс; для других чатов — 08:24/08:29Z). Это доказывает, что исключение
  слоя — свойство боевого рантайма, а не только harness-процесса.
- Fallback-вызовов нет (`_post_fallback` = 0).

## 3. Частотный факт по ответам бота (честно, с ограничением)

- **`bot_replies`** (единственный живой текст-стор ответов бота; TTL 3600 с лениво,
  cap 200): в окне волны на момент уборки — ровно 1 строка (наш тестовый ответ, мата
  нет); на момент пробы вся таблица для чата — **0 строк**. Последний реальный ответ
  прод-процесса в чате — **08:02:12Z**.
- Journal даёт объём, но не текст (R17): за день **18** строк `[direct] reply sent |
  chat=-1002661910336` и 18 `[direct] l2 writer | …` (окно 04:55–08:02Z).
- Единственный durable-архив собственных сообщений бота в `smart_messages` — импорт
  истории: последняя строка **2026-09-04** (40 строк; 13/40 с матом) — это **старая
  персона** (до эпохи SOUL-1/Core), не текущее поведение.
- **Вывод:** ретроспективный подсчёт мата по «последним 10–20 ответам» на проде
  **невозможен** (нет durable-текста; TTL 1 ч). Текущая эпоха представлена только
  контролируемыми ходами: Ф0 (1/1 без мата) и ACCEPTANCE-94 (без мата). Измерение
  20–30 примеров остаётся за EXP-ACCEPT.LIVE-SET (Ф6) — и там harness должен сам
  сохранять тексты ответов.
- Контроль, что мат в принципе достижим у этого провайдера: архив 2026-09-04 (та же
  модель/чат, старая персона) содержит матерные ответы → провайдер не фильтрует мат.

## 4. Классификация (§3.5)

| Класс | Вердикт | Доказательство |
|---|---|---|
| **`composer_excluded`** | **ДА — основная причина** | манифест/события: `expression:expression_absent` (durable mca_events id 72922 + journald прод-процесса); код: `PromptPlan.expression` задаётся только в preview (`web/api/speech.py:1458`, writer `speech_ui_preview`), боевые сборки (`services/direct_chat_service.py:4373–4398`, `services/mca_authorial_speech.py:96–135`) `expression=` не передают |
| **`policy_not_injected`** | **ДА (следствие)** | `Expression_Settings` = 0 в payload; `rendered_text` владельца (в т.ч. «Мат: допустим») до LLM не доходит |
| `model_ignored_instruction` | нет | инструкции частоты не было вовсе (только мягкие разрешения Core/канона); нейтральный micro-ответ им не противоречит. Проверка следования инструкции возможна лишь после подключения (Ф6) |
| `postprocess_changed` | нет | egress-guard `sanitize_outgoing` режет только reasoning-теги/`fact:/msg:`/target-маркеры (`EXTRA_PATTERNS=()`); `style_policy.RULE_KINDS` без profanity; в `reply_postprocess/negative_constraints/telegram_send/grounding_validator` profanity-правил нет (скан 0) |
| `provider_limitation` | нет доказательств | wire-вызовы прошли штатно (без фильтрации/отказов); архив 2026-09-04 содержит мат в ответах бота того же чата |
| `unknown` | не требуется | причина установлена payload-трейсом |

**Что это значит для плана:** подтверждение находки PM — слой Expression **никогда не был
подключён** к живым сборкам; «мата нет» объясняется `composer_excluded`/`policy_not_injected`,
это **не регрессия**. Дефект = ADD-EXP §3.2 (WIRING). UI уже честно показывает
`runtime_wired=false`. Для Ф6: harness обязан сам сохранять текст ответов (прод не хранит их).

## 5. Уборка и состояние прода

- Тестовое сообщение бота mid **1166228** — **удалено**; синтетические строки сняты
  (`bot_replies` ×1, `throttle_state` ×1); residual = 0 (`cleanup-register.json`).
  Строки `smart_messages` для синтетического mid не было (smart_removed=0).
- Оставлено как диагностика (не сообщения): события `mca_events` от harness-хода
  (вкл. id 72922), строки PG `llm_usage_events` хода (l1_planner 1117/109; l2_writer
  7885/20 токенов).
- Прод не тронут: HEAD/версия/PID/NRestarts без изменений, `TRACKED_MOD=0`, healthz ok;
  в окне волны журнал: 0 `database is locked`, 0 SKIPS; 5 ERR за день — пре-существующие
  (summary L2 ×2, SQLite-контеншн/INCIDENT окна ACCEPTANCE-94 09:14Z).

## Файлы

- `probe-after.json` — PG/SQLite read-only проба (документы, gates, события, usage);
- `probe-replies.json` — ответы/авторы `smart_messages`, `bot_replies`, мат-скан;
- `f0-live.json` — payload-дамп хода (полный system/user l2_writer, хэши wire-вызовов,
  манифест-трасса, API-вид Expression, ответ и mid);
- `cleanup-register.json` + `cleanup-spec.json` — уборка;
- `journal-f0-excerpt.txt` — журнал (фильтр) + счётчики; `live-harness-stdout.txt` — stdout harness;
- `harness/` — исходники контролируемых вызовов (`f0_probe.py`, `f0_probe2.py`,
  `f0_live.py`, `f0_clean.py`); bootstrap `f0_base.py` = проверенный
  `accept94_base.py` (sha256 в `checksums.txt`; SSH-раннеры с креденшелами не промотируются);
- `checksums.txt` — sha256 артефактов.

**Техническая заметка (для Reviewer):** в `f0-live.json` блок `manifests` = `null` —
harness запросил манифест по последнему correlation_id хода, тогда как сборка шла под
cid `c448d16a8326` (см. `llm_calls`). Поэтому манифест-трасса взята из событий самого
хода (`captured_logs` + durable `mca_events` id 72922), а не из реестра манифестов;
payload-доказательство (полный system/user) сохранено полностью.
