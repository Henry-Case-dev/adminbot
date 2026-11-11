# p0-init-meme-ux-diag — read-model (c087253d / 2.58.188)

ARCHITECT_ADJUSTMENT_REQUIRED. Не новый продукт. Источник: `plans/owner_inputs/2026-11-11-p0-init-meme-ux-diag-corrective-excerpt.md`. Код сверен только через `git show c087253d`. Внешние контракты не требовались: механика репозиторная.

## 1. Read-model
Один аддитивный объект `axes` на механизм внутри уже существующего `collect_mechanism_diagnostics` (`services/initiative_diagnostics.py`, `schema_version` остаётся 1). Механизмы: `text_initiative` и `meme`. Ручной `/meme` — тот же мем, `mode=manual`, не третий тумблер. UI не собирает оси из флагов. Поля `ready`/`available` не перегружать и не читать как «включено». Боевой путь при нечитаемой настройке остаётся fail-closed; витрина при этом не имеет права рисовать OFF.

**configuration** — `enabled: true|false|null`, `source`, `scope` (`global|chat|mixed`), `reason` (только если не разрешено или неизвестно).
- Текст, уже есть: `module_registry.effective_gate("initiative")` + `observer_enabled()` + `chat_observer_enabled`. `false` только при явном OFF мастера, env, observer или чат-тумблера. Нечитаемая ось → `null` (сегодня `_initiative_on` схлопывает сбой в false — для витрины это запрещено).
- Мем, уже есть: те же гейты + `MemeSettings.enabled`. `image_dependency.module_enabled=false` — тоже configuration, source `image_module`. Провайдер, schema и health сюда не входят.

**health** — `ok|degraded|error|unknown` + `dependencies[{name,state,source}]`. Без нового probe и без LLM.
- ok: журнал и бронь читаются; для мема image configured. Текст image не требует.
- degraded: уже есть — `publication.coordination=degraded` / нет таблицы брони.
- error: image not configured / unhealthy, журнал нечитаем.
- unknown: сбой чтения или нет снимка. Производители: `image_dependency`, `ledger.table_present`, `PublicationCoordinator.precheck`.

**readiness** — `ready|waiting|busy|blocked|unknown`, `reason`, `reason_class`, `next_eligible_at` (unix|null), `next_basis`.
- ready: можно рассматривать сейчас. Не обещание публикации.
- waiting: cooldown, `not_enough_messages`, quiet hours, quota, lottery miss, следующий тик, координация, отложенный артефакт, живой manual priority.
- busy: свежий inflight или claim `claimed|sending` с `expires_at` в будущем.
- blocked: `enabled=false` или жёсткий отказ прав/schema, который не является ожиданием.
- unknown: no data / read failed.
- `next_eligible_at` только из уже посчитанного факта: meme cooldown = `last_provider_ts+cooldown_seconds`, если оба есть и остаток > 0; конец quiet hours из уже разобранного `HH:MM-HH:MM`; quota = `day.next_reset_iso`; cross-type = чужой `last_publish_ts+interval`; живой `manual_priority_until`; text `next_eval_ts` только если он в будущем и basis=`eval_interval`. Иначе null. Не отдавать `availability().next_check_ts`: при отсутствии кулдауна он подставляет `now`.

**last_attempt** — `at`, `mode` (`manual|auto|unknown`), `run_id`, `outcome`, `stop_stage`. Мем: терминальная строка группы `job_id` журнала попыток. Текст: группа `mca_events.trace_id`. `mode` из `events[].mode` или detail JSON терминальной строки, не из позднего publication-fact. Нет строки → null.

**last_delivery** — `status: confirmed|unknown|never`, `at`, `destination` (chat_id), `message_id`. Подтверждение только запись `record_delivered_output` / `mca_bot_outputs` с `tg_message_id`. Событие sent без id → unknown. Пусто → never. `considered` / `generated` / `deferred` доставкой не являются.

## 2. Разделение
Не ставят `enabled=false`: cooldown, `not_enough_messages`, quota, quiet hours, lottery miss, ожидание тика, координация публикации, deferred wait, unhealthy провайдер, отсутствие schema, ошибка загрузки. `No Data` и сбой fetch: `enabled=null`, `health=unknown`, не OFF. «Разрешено» читает только `configuration.enabled`. «Сейчас: отключён» допустим лишь при `enabled=false`. Истёкший `manual_priority_until` (`until<=generated_at`) и просроченный `expires_at` не текущий блок: precheck уже считает `manual_active`, но снимок и `initiativeCoordination` показывают сырой until. `ready` не копировать в «опубликует»: молчание L1 — исход попытки, не OFF и не error.

## 3. Идентичность (общий корень)
Новых колонок и таблиц нет. Родитель — существующие `job_id` журнала мема и `trace_id` `mca_events` (§17.1: trace_id = run/correlation).
- Мем: в `consider_chat` mint `jid` сразу после загрузки cfg, до любого `skipped()`. Сейчас `jid` создаётся после гейтов initiative/chat/enabled/deferred/image/schema, и `_finish` пишет пустой `job_id`. Агрегатор при пустом `job_id` делает ключ `row:{attempt_id}` — отсюда две «попытки». Каждый ранний `skipped` обязан нести тот же `job_id`.
- Дочерние вызовы, не новый журнал: `_default_summarize` / `_default_joke` получают `correlation_id="{jid}#meme_summary"` и `"{jid}#meme_joke"` вместо `uuid4`. Image остаётся `correlation_id=jid` (родитель; `image_generation` уже пишет его в `run_id`). Бронь: `holder_ref=jid`. Доставка: `correlation_id=jid` в `record_delivered_output`.
- Текст: per-chat `run_id` в начале оценки чата, не cycle `task_jobs.job_id`. Все `_emit` передают `trace_id=run_id`. Сейчас claim-события кладут `entity_id=claim_id`, а перенос в `trace_id` есть только у `initiative_decided|sent|reacted`. Child: `{run_id}#digest|#eval|#writer`.
- Чтение: непустой родитель — единственная склейка. Пустой исторический `job_id`/`trace_id` не склеивать по времени или тексту; метка `incomplete_historical`. `mode` писать в уже существующий detail JSON терминальной строки (`manually_triggered` есть на `AttemptResult`, в строку журнала не попадает).
- `/meme`: в `finally` терминального исхода погасить `manual_priority_until` существующим стейтментом брони. Даже без гашения истёкший until не рисуется как блок.

## 4. Чат
`mechanism-diagnostics` и `publications` уже требуют `X-Chat-Id`, проверяют доступ и возвращают `chat_id`. Контракт: `payload.chat_id` равен запрошенному; каждая строка только `WHERE chat_id=?`; чужой scope не подмешивать. Клиент до await фиксирует `{epoch, chatId}` и применяет ответ только если `scopeEpoch` совпал и `payload.chat_id===chatId`. Смена шапки сразу очищает карточки и журнал. `loadMemeDiagnostics` при `memeDiagBusy` сейчас молча выходит и оставляет старый снимок — запрещено: один in-flight и один хвост на последний epoch. Сравнение чатов — два независимых payload, без безымянного агрегата.

## 5. Обзор
Своя тёмная система. Паттерн: обзор → попытка → этапы → уже сохранённые факты. Над сгибом: выбранный чат, TZ чата (`resolve_timezone`), `generated_at`, «Обновить». Две равные карточки. Строка 1: имя · Разрешено · Сейчас · чип ошибки только при `health=error`. Строка 2: одна причина readiness и время только при `next_eligible_at`, с TZ. Строка 3: проверка ≠ попытка ≠ подтверждённая отправка; своя квота (текст: 0 = без лимита; мем: 0 = предел, как `quota_block`). Действия ведут в существующие «Настройки» и «Публикации» с `run_id`, чатом и видом. Полоса координации только при живом конфликте, живом manual priority или degraded. Ниже 5–10 попыток; полная история — ссылкой. В трассе только фактические этапы механизма; невыполненное = «не выполнялся», не `skipped`-запрос. Полный текст промпта не начинаем сохранять: если его нет в существующем detail/event — «полный текст исторически не сохранялся». Секреты не показывать. Техкод только в детали рядом с русской подписью.

## 6. Приёмка
- configuration: cooldown и `not_enough_messages` при `enabled=true` не дают ВЫКЛ; нечитаемая ось → null, не false.
- health: No Data и ошибка загрузки не красят OFF; degraded брони ≠ «конфликта нет».
- readiness: ready не обещает публикацию; lottery и тик без штампа → `next_eligible_at=null`; истёкший until не waiting.
- last_attempt: ранний `/meme` — одна строка, `mode=manual`, `stop_stage` = первый гейт; пустой исторический `job_id` не склеен.
- last_delivery: confirmed только с `message_id`; sent без id = unknown; пусто = never.
Доказательство: unit проекции осей и группировки (пустой `job_id`, cooldown, expired until); API-тест равенства `chat_id` и отброса чужого scope. Живой снимок двух чатов — отдельная read-only проверка, не публикация в рабочие чаты. Визуал Playwright + Browser Use — приёмка сборки, не этот дизайн.

## 7. Не-цели
Нет новой БД, state machine, диагностического конвейера, LLM-проверок ради наблюдаемости, архива промптов, правок промптов, моделей и сохранённых настроек, второго пайплайна мемов и смены решения LLM.

SERIALIZE: `meme_initiative.py`, `initiative_observer.py`, `initiative_diagnostics.py`, `initiative_publications.py`, `publication_coordination.py`, карточки `web/app.js`. Live-снимок двух чатов — READ_ONLY_PARALLEL. Риск R2. Следующий шаг: снять live-строку ниже, затем Builder правит проекцию и mint `run_id`, не обходя её клиентской реконструкцией.

DESIGN READY
Live до кода: effective-config обоих чатов; last_attempt, last_delivery, message_id, quota, cooldown, последний provider call, manual_priority active vs expired; обрыв `/meme` по сегментам update→RBAC→delete→marker→gates→messages→LLM A/B→image→claim→Telegram; `payload.chat_id` при медленном переключении шапки.
