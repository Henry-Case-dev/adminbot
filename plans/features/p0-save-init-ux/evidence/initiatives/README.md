# P0 INIT-FIX — инициатива: диагностика и исправление реальных блокеров

Дата: 18.10.2026 · Прод на момент диагностики: `d59fab94` (2.58.89), сервис
`admin_bot` active · Диагностика прода — ТОЛЬКО чтение (два коннекта:
основной дамп + целевой recon), без записей/рестартов/публикаций.

Источник требования: `plans/features/p0-save-init-ux/source-p0-hotfix-2026-10-18.md`
§1 («Инициатива — автономные сообщения не появляются»), §4 (приёмка).

Артефакты:
* `prod-readonly-dump-01.txt` — полный read-only дамп (SQLite + PostgreSQL);
* `prod-readonly-dump-02-recon.txt` — целевой recon по решению/воронке;
* `red-before-fix.txt` — RED (новый набор тестов против кода без фиксов);
* `green-after-fix.txt` — GREEN (финальный кандидат);
* `candidate-fingerprint.txt` — SHA256 изменённых файлов + базовый HEAD;
* `ui-before/`, `ui-after/` — Playwright-проба админ-статуса (до/после);
* `verdict.md` — краткий вердикт по четырём пунктам ТЗ.

---

## 0. Что показал прод (факты, не гипотезы)

| Показатель | Значение | Файл-источник |
|---|---|---|
| Мастер-гейты | `flags.initiative_enabled=true`, `flags.initiative_observer_enabled=true`, `initiative.enabled=true`, `flags.intent_heartbeat_enabled=true`, `flags.intent_decision_enabled=true` | dump-01 `PG_BOT_SETTINGS` |
| Профиль чата −1002661910336 | наследует глобальное: `normal`, `min_gap=7200`, `max/day=6`, `eval_min_interval=2700`, `eval_min_messages=8`, бюджет оценок 12 | dump-01 |
| Тики | `initiative.observe` — 778 задач, все `completed`; heartbeat-штамп живой (`due=0, enabled=true`) | dump-01 |
| Курсор наблюдателя | `cursor_message_rowid=155734` при `MAX(id)=2350637` → **лаг 2 194 903 сообщения**; 200 строк / 300 с ≈ **38 суток** догоняния | dump-01 |
| «Наблюдено» | `observed=135869, eligible=135869` — это **древняя история**, не живой чат; `day.observed=17073` | dump-01 |
| Причины пропусков | `eval_not_due=701`, `not_enough_messages=70`, `min_gap=4`, `direct_address_seen=1` | dump-01 |
| Оценки/поводы | `evals=2`, `opportunities=2`, `silent_decisions=2`, `sent=0`, `writer_unavailable=0` | dump-01 |
| События воронки | `initiative_observer_scan` ×777, `initiative_opportunity` success ×2, `initiative_decided` silent ×2, `initiative_observer_diagnostic` **failed ×3** (ложное «24 ч ноль поводов» на мусорных счётчиках) | dump-01 |
| Решения (полные строки) | `status="reply"`, `outcome=silent`, `reason_code="default"`, `component=intents`, `stage=new_message` — дважды (kind `useful_info` и `development`) | dump-02 |
| Выводы бота за 7 суток | `direct_reply` ×127, `rich_message` ×26, `media_caption` ×7 — обычный Direct каждые десятки минут | dump-01 |
| Намерения | `mca_intents` пуст (0 строк) — durable intent ни разу не создавался | dump-01 |
| RBAC | владелец `5885953495` = `admin` (global_admin, wildcard); чат-грант `local_admin` у `1313107079` | dump-01 |

## 1. Вердикт по четырём пунктам ТЗ

### 1.1. Исторический курсор — **ПОДТВЕРЖДЁН**
`enqueue_observe` стартует с `cursor_message_rowid=0`, а сканирование идёт
`WHERE id > cursor ORDER BY id LIMIT 200` глобально по `smart_messages`
(2 028 412 строк, «многолетний» корпус). Факт прода: курсор 155 734 при
максимуме 2 350 637 → наблюдатель годами «пережёвывает» историю, живой чат не
наблюдается, диагностические счётчики (`observed`, «24 ч ноль поводов»)
наполняются древними репликами.

**Исправлено:** курсор «подтягивается» к живому началу переписки
(`SCAN_FRESH_LOOKBACK_SECONDS=6 ч`, но не меньше последних
`SCAN_FRESH_MIN_ROWS=200` строк), только вперёд, строка-якорь не теряется.
История не удаляется: по древним обсуждениям инициатива не генерируется, а
память/дампы не затронуты. Наблюдаемость: счётчик `scan_anchored` +
событие `initiative_observer_scan` со `stage=anchored`.

### 1.2. Одно обращение к боту выбрасывало окно целиком — **ПОДТВЕРЖДЁН**
`_window_addressed_to_bot()` использовал `\bбот\w*` (совпадает с «ботаник»,
«ботва», «боты») и при единственном совпадении отбрасывал ВСЁ окно
(`direct_address_seen`). В русском чате это глушит инициативу.

**Исправлено:** реплики классифицируются отдельно
(`addressed_to_bot`: падежные формы «бот/боту/бота…», «ботик/ботяра»,
`@username` бота; часть другого слова — «робот», «ботаник» — не считается);
окно отбрасывается ТОЛЬКО если обращений — все реплики. Смешанное окно
идентично канону доходит до оценки (system-промпт уже запрещает считать
обращение к боту поводом), а от конкуренции с прямым запросом защищает
существующий recheck `direct_pending` непосредственно перед отправкой (§1.4).

### 1.3. Cooldown считался от любого вывода бота — **ПОДТВЕРЖДЁН**
`_last_bot_output_age()` читал последний доставленный вывод ЛЮБОГО вида
(`mca_bot_outputs`), а `min_gap=7200` сравнивался с ним. В живом чате
`direct_reply` каждые десятки минут (прод: 127 за 7 суток) постоянно сбрасывал
паузу инициативы; в дампе видны пропуски `min_gap`.

**Исправлено:** два разных слоя — антифлуд после ЛЮБОГО вывода
(`ANTI_FLOOD_AFTER_BOT_OUTPUT_SECONDS=300`, причина `anti_flood`) и cooldown
инициативы `initiative.min_gap_seconds` ТОЛЬКО по выводам
`output_kind='initiative_reply'` (причина `min_gap`, как и раньше).
Диагностика ворот (`chat_block_state`) показывает оба возраста отдельно.

### 1.4. Админ-статус `restricted` / «нет разрешённого чата» — **ПОДТВЕРЖДЁН (маппинг/состояние, не RBAC)**
RBAC исправен: владелец — global_admin с wildcard, `can_access_chat` = true
для чата PERMsoc. Причина в другом: `intent_snapshot` возвращал ОДНО и то же
`state="restricted"` и когда чат ВООБЩЕ не выбран (`X-Chat-Id` отсутствует →
`chat_id=None`), и когда доступа к выбранному чату нет. Именно первое владелец
и видел: при старте админки (область «Весь бот») блок «Инициатива» писал
«Нет разрешённого чата — данные инициативы не раскрываются», что читается как
отказ прав. Дополнительно: `initiativeFunnel`/W5-панель и «Проверить
инициативу» в этом состоянии были недоступны.

**Исправлено:** состояния разделены — `no_chat` («чат не выбран») и
`restricted` («нет доступа к выбранному чату»); UI получил оба текста,
воронка по-прежнему не раскрывает данные без чата. Проба `ui-before`/`ui-after`
воспроизводит симптом и подтверждает фикс (в т.ч. визуально в реальном Chrome).

## 2. Дополнительный блокер, найденный по ходу (вне четырёх пунктов ТЗ)

**Эфемерный повод терял свой контекст.** Наблюдатель вызывает существующий
единый вход `handle_initiative` с кандидатом без durable-намерения
(B01.2: opportunity ≠ intent). Внутри `handle_initiative` строка намерения
бралась ТОЛЬКО по `decision.intent_id`; для observer-повода её нет →
`plan_initiative_decision(chat_id, {})` и `generate_initiative_reply(chat_id, {})`
получали «Намерение (kind=unknown, origin=unknown): цель не указана», а
`SendRecheck` работал с пустым контекстом (проверки фактически не выполнялись).

Прод-подтверждение: оба решения — `status="reply"` (решение «говорить») с
`outcome=silent` и без событий `initiative_writer_generated`/`recheck`/`sent`.
Такой комбинации соответствует ровно ветка «L1 отказался»
(`l1_silent`/`l1_unavailable`); при этом событие записало `reason_code="default"`
(код решения), и настоящая причина отказа в воронке терялась.

**Исправлено:**
* `handle_initiative(..., opportunity_row=...)` — наблюдатель передаёт
  `goal/kind/origin/created_at/refs`, Writer/L1 видят реальную цель;
* `created_at = момент повода` → существующий `SendRecheck` (`direct_pending`,
  `already_answered`, `context_version`) реально работает и для observer-повода;
* `note_decision(..., reason_code=...)` — событие воронки несёт истинную
  причину отказа стадии (`l1_silent`, `l1_unavailable`, `recheck_demoted`,
  `already_answered`, `direct_pending`, `intent_closed`, `delivery_not_text`,
  `writer_failed`), владелец видит её в «Статусе» (`last_decision.reason_code`).

## 3. Доказательства RED → GREEN

Набор `tests/test_p0_initfix_initiative_observer.py` (10 тестов) прогнан
против кода БЕЗ фиксов и против финального кандидата:

* RED (`red-before-fix.txt`): `7 failed, 3 passed` — падают именно свидетели
  блокеров (курсор, ложное «ботаник», выброшенное смешанное окно, cooldown от
  Direct, отсутствие антифлуда, потеря повода, неработающий recheck);
  «зелёными» остаются защиты: отсутствие отката курсора, окно из одних
  обращений к боту, cooldown после инициативы.
* GREEN (`green-after-fix.txt`): `405 passed` (набор P0 + B01 + SOUL-1 W5 +
  F6 + mca-09 + mca-13 + module-registry + status + direct + C06A-status;
  прогон привязан к `candidate-fingerprint.txt`).

Смежные наборы, прогнанные по затронутым швам: `test_asap8_f6_initiative`,
`test_mca09_intents_*` (6 файлов), `test_mca13_event_contract_round1027`,
`test_mca10b_*` (4), `test_asap8_v6_c06a_status_ui`, `test_status_service`,
`test_soul1_w5_*`, `test_direct_chat`, `test_asap8_v6_wc_direct_matrix`,
`test_aliases_render_round1024`, `test_asap7_module_completeness`,
`test_asap8_f5_module_truth`, `test_asap8_v6_d14_help_sync`,
`test_status_section_ui_merge_round1019`, `test_webapp_status_control`,
`test_cfg02a_image_quota_ui`, `test_budget_settings_round1019`,
`test_104_backend_additions` — 0 новых падений (упавшие
`test_asap7_direct_settings::test_migration_v35_idempotent_twice` и
`::test_backup_guard_fires_before_pending_step` падают и на чистом HEAD —
pre-existing, к фиксу отношения не имеют).

## 4. Доказательство «цепочка способна дойти до отправки» (без публикации в чат)

`test_opportunity_carries_context_into_writer_and_sends`: синтетический чат →
оценка окна (fake LLM) → решение → L1/L2 (fake Writer, фиксирующий переданную
строку намерения) → recheck → отправка через fake-бот (НЕ Telegram) →
`counters.sent == 1`, событие `initiative_sent`, в ledger появляется
`output_kind='initiative_reply'` (основа cooldown инициативы). Дополнительно
`test_pending_direct_request_stops_observer_initiative` доказывает, что при
прямом запросе, пришедшем во время подготовки, отправка отменяется
(`direct_pending`), т.е. безопасность «инициатива не соревнуется с Direct»
сохранена. Ни одной публикации в рабочий чат не выполнялось.

## 5. UI/визуальная проверка

Playwright (реальные `web/index.html` + `web/app.js`, детерминированные
стабы, повторяющие серверную семантику scope; снимки кадрируют САМ блок
«Инициатива», а не верх страницы):

* `ui-before/`: global-вид → «нет разрешённого чата» (симптом владельца),
  `global_no_false_restricted=false`; кадр `01_global_no_chat.png` и кадр
  недоступного чата `03_denied_restricted.png` **побитово совпадали** — две
  разные ситуации (чат не выбран / нет прав) рисовались одинаково, это и есть
  дефект маппинга;
* `ui-after/`: global-вид → «чат не выбран» + честное пояснение
  (`01` изменился, `01 != 03`); недоступный чат (RBAC) → «Нет доступа к
  выбранному чату» (`03` изменился); доступный чат PERMsoc →
  намерения/воронка/W5-панель (`02` совпадает с before — этот путь фиксом не
  менялся, регрессии нет); горизонтального переполнения нет; консоль без
  ошибок.

Осмотр в реальном Chrome (Browser Use): global-вид → «чат не выбран»;
чат PERMsoc → «данные», 2 намерения, воронка наблюдателя, W5-предупреждение с
человеческой формулировкой, кнопка «Проверить инициативу», переполнения нет.

## 6. Остаточные риски и сопутствующие находки

* Ложное диагностическое событие «24 ч ноль поводов» (`initiative_observer_diagnostic`,
  3 срабатывания) накапливалось на исторических счётчиках — после подтяжки
  курсора `day.observed` отражает живой чат; сам порог не менялся.
* `_f6_chat_facts` (решения/recheck) продолжает использовать прежний
  `_BOTWORD_RE` (`\bбот\w*`) для «прямого обращения» — с новым `created_at`
  повода это окно ограничено секундами генерации, поэтому ложные «ботаник»
  здесь безопасны; отдельного рефактора не делалось (вне объёма P0-среза).
* Соседние чаты (второй групповой чат) наблюдаются тем же механизмом; их
  профиль/scope не менялись.
* Прод не выкатывался этой полосой (коммит не делался): evidence привязано к
  локальному кандидату (`candidate-fingerprint.txt`).
