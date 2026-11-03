# P0 — готовый мем не отменяется из-за нового сообщения (+ P0.5 пустой потолок = авто)

- Ветка: `fix/p0-publication-stale`, база: `7536df96`
- Кандидаты: `b95b7363` (P0/P0.5) → `46edd36e` (B1/B2/B3 по ревью) →
  **фикс B4** (см. §9). Ревью: `plans/features/p0-meme-publication-hotfix/review.md`
  (Needs Fixes → Re-review 2: Needs Fixes только B4), решение Architect по B1:
  `plans/features/p0-meme-publication-hotfix/arch/deferred-publication.md`.
- Источник требований: `plans/owner_inputs/2026-11-03-hotfix-meme-publication-initiative-ui.md`
  §1.1–§1.4 (P0 и P0.5). P1 (перекомпоновка UI «Модули → Инициатива») —
  отдельный трек, здесь НЕ делался.
- Область: `services/meme_initiative.py`, `services/initiative_observer.py`
  (ярлыки), `services/publication_coordination.py` (только B3),
  `handlers/meme_command.py`, `web/api/routes.py`, минимальное состояние
  карточки в `web/app.js`; тесты. Схема БД не менялась, новых таблиц нет.
- Деплой не выполнялся.

## 1. Инцидент и корень проблемы

Живой инцидент: бот пишет «Переписка в чате изменилась за время генерации — мем
не отправлен», админка показывает `publication_stale`, готовое изображение
выбрасывается.

Корень (до правки, `services/meme_initiative.py`, база `7536df96`):

- `services/meme_initiative.py:1585-1587` — на старте генерации читался
  watermark окна (`MAX(id)` в `smart_messages`);
- `services/meme_initiative.py:1768-1779` — после генерации, уже ПОСЛЕ взятия
  брони публикации, watermark перечитывался и сравнивался:
  `int(current_watermark) != int(window_watermark)` →
  `_drop_claim(SKIP_PUBLICATION_STALE, detail="window_changed")`.

То есть любое новое сообщение в чате (в том числе в автоматическом меме и в
ручном `/meme`) превращалось в «мем устарел». Это сравнение двух timestamp/id,
а не доказанная утрата актуальности — ровно то, что §1.2.2/§1.2.7 запрещают.
Готовый артефакт при этом уже был оплачен (провайдер вызван), а в чат уходил
ложный текст ошибки.

## 2. Что сделано (P0 §1.2)

1. **Снапшот источника** (`SourceSnapshot` + `build_source_snapshot`) —
   фиксируется один раз, в начале генерации, и больше ни с чем не сравнивается:
   `chat_id`, `run_id` (= job), `mode` (`manual`/`automatic`), `purpose`
   (`meme_manual`/`meme_initiative`), `request_ref` (id сообщения `/meme` или
   инициативный job), `message_ids`, `message_count`, `first_id`/`last_id`,
   `digest` (sha256 по id+версиям текстов), `captured_at`. Durable-вид
   (`as_dict`) хранит id/числа/коды и НЕ хранит тексты сообщений (R17).
2. **Проверка watermark удалена целиком.** Ни `latest_message_id`, ни
   `MAX(id)`, ни «общий watermark» больше не участвуют в решении о публикации.
   Параметр-шов `watermark_reader` удалён из `consider_chat`.
3. **Ручной `/meme`**: после авторизованного запроса и успешной генерации
   изображение доставляется даже если чат ушёл вперёд; повторный `/meme` и
   вторая генерация не требуются. id сообщения команды передаётся в
   `consider_chat(request_ref=...)` и попадает в снапшот/события.
   Reply-цель не используется осознанно: сообщение команды удаляется ПЕРВЫМ
   сетевым действием обработчика (замороженный порядок `arch §10.1`,
   дополнение владельца 03.11.2026), поэтому цели для reply физически нет —
   доставка идёт новым сообщением, как и раньше.
4. **Автоматический мем**: остались только настоящие проверки — тумблеры
   (перечитываются по факту, `disabled_by_setting`/`initiative_disabled`),
   наличие исходного материала (`source_material_gone`), техническая
   пригодность output (в т.ч. новый случай «провайдер сказал ok, но картинки
   нет» → `image_generation_failed`/`empty_content`), существующая
   бронь/ledger и существующий publish-гейт.
5. **Коллизия координации**: ручной путь ДОЖИДАЕТСЯ разрешённого слота
   существующим durable-механизмом (`PublicationCoordinator.acquire(...,
   wait_for_sending=MANUAL_IN_FLIGHT_WAIT_SECONDS)` — release-event, который
   уже был в коде) и отправляет ТУ ЖЕ картинку; автоматический путь не ждёт
   (иначе проход инициативы висел бы на чужих слотах) и фиксирует точную
   причину, не расходуя квоту дважды.
6. **Идемпотентность/рестарт**: повтор того же `job_id` не отправляет дубль и
   не делает второй платный вызов (`provider_called` + `job_already_counted`);
   неизвестный статус доставки не выдаётся ни за «отправлено», ни за
   «отменено» — `delivery_unknown` (существующий протокол брони и
   `recovered_delivery_unknown` теперь ещё и виден событием/фактом).
7. **Ошибка соответствует факту**: `publication_stale` остался в таксономии
   только для чтения исторических строк журнала и больше НИКОГДА не
   эмитится; ярлык переписан («результат признан потерявшим актуальность»).
   После успешной доставки отмена не сообщается. Автоматический кандидат не
   пишет объяснений в чат (текст ошибки есть только у ручного `/meme`).
8. Ни LLM-судьи на send, ни новых жёстких таймеров, ни бюджетов, ни
   per-chat/имя-хардкодов, ни postgen-перегенерации не добавлено.

### Матрица решений (код → когда выдаётся → что означает)

| Код | Когда | Факт |
|---|---|---|
| `sent` (`publication_sent`) | sender вернул сообщение | доставлено, `delivered: true` |
| `delivery_unknown` | sender бросил исключение ИЛИ бронь восстановлена из `sending` | доставка не доказана и не опровергнута |
| `publication_conflict` | чужая бронь/интервал/приоритет `/meme` (в т.ч. гонка после генерации) | слот занят другим механизмом |
| `publication_in_flight` | чужая активная отправка (`sending`) | ждём/не отправляем |
| `publication_expired` | наша бронь перестала быть нашей (`begin_sending` отказал) | слот потерян, дубля нет |
| `disabled_by_setting` (`detail: module_disabled_during_generation`) | мем-модуль выключили, пока рисовалось | содержательная отмена |
| `initiative_disabled` (`detail: *_during_generation`) | инициативу/чат-гейт выключили во время генерации | содержательная отмена |
| `source_material_gone` (`detail: source_messages_deleted`) | ни одного исходного сообщения снапшота не осталось | доказанная утрата материала |
| `publish_blocked` | publish-гейт закрыт (`detail` = реальная причина) | гейт, не «устаревание» |
| `publish_blocked` (`detail: publisher_not_bound`) | не привязан отправитель | доставка технически невозможна |
| `image_generation_failed` (`detail: empty_content`/причина провайдера) | провайдер не дал изображение | генерация не удалась |
| `no_joke_budget` (`detail: prompt_over_ceiling:…`) | фиксированный L не оставляет места | конфигурация, ДО генерации |
| `publication_stale` | **не выдаётся** (исторические строки) | — |

Порядок проверок перед отправкой: output годен → тумблеры (только авто) →
исходный материал существует → атомарная бронь (ручной ждёт слот) →
publish-гейт (только авто) → `claimed→sending` → sender.

## 3. События (§1.3)

`meme_initiative.MEME_EVENTS` (durable, в фактах терминальной строки журнала
попыток и в `GET /api/initiative/meme-settings → delivery.events`):

`source_snapshot` → `digest_ready` → `joke_ready` → `image_ready` →
`publication_requested` → `publication_sent` | `publication_deferred_conflict` |
`publication_cancelled` / `publication_failed` | `delivery_unknown`.

Каждое событие: `name`, `at` (время попытки, инъекция часов), `run_id`, `mode`
(`manual`/`automatic`), `purpose`, `source` (слой промпта/происхождение),
`reason`, `detail` (числа/коды/link-safe строки, без текстов сообщений),
`after` — ссылка на предыдущий этап, и `delivered` только у публикационных
(`true`/`false`; отсутствует у `image_ready`, у `delivery_unknown` не
выставляется вовсе = «неизвестно»).

Журнал попытки: терминальной строкой теперь считается РЕАЛЬНЫЙ итоговый этап
(`result.stage`), а не последний счётчик — иначе факт доставки уезжал в строку
`skipped`. Плоский текстовый `detail` терминальной строки сохранён ВНУТРИ JSON
ключом `detail` (витрина уже парсила `detail` как JSON фактов).

## 4. P0.5 — пустой «Потолок длины» = АВТО (§1.4)

Три состояния во всём тракте:

- **Пусто/`null`/пробелы = `auto`.** API отличает «поля нет в теле» (не менять)
  от «поле пришло пустым» через `model_fields_set`: пустое значение =
  удаление чатового переопределения (`removals`), а не запись `null`/`0`.
- **Положительное целое = `fixed`.** `L` (ceil) — минимум кандидатов
  (`explicit_override` → `admin_setting` → `model_capability`).
  `T` = длина РЕАЛЬНО зарендеренного production-renderer'ом
  `render_image_prompt(template, "")` промпта (разделители/обвязка входят),
  `J = max(0, L - T)`.
- **Некорректный ввод** (текст, дробное, отрицательное, > 8000) = `422` с
  точным сообщением в форме Pydantic-списка (`loc: ["body","length_limit"]`),
  клиент показывает ошибку у поля и НЕ отправляет запрос.

Историческая `0` = `auto` (совместимость): читается как «не задано», при
сохранении 0 не записывается и не стирает untouched-значение.

Runtime: при `auto` числового предела НЕТ — директива длины в промпт этапа B не
подставляется, прикол не обрезается, выжимка не трогается, искусственные
`0/800` не появляются. Код `length_limit_unknown` больше не эмитится (оставлен
для исторических строк). При `fixed` проверка «нет места» стоит ДО выжимки и
ДО провайдера, а итоговый промпт сверяется с `L` через `image_prompt_fits`.

Витрина: `length_limit.mode` (`fixed`/`auto`), `joke_budget = null` в авто,
`ceiling = null`, источник `auto`. Карточка показывает «автоматически»,
«Потолок итогового промпта: не задан», «Доступно для прикола: определяет
провайдер» и «источник потолка: не задан (авто)».

## 5. Тесты

Новый контрактный набор: `tests/test_p0_meme_publication_hotfix.py`
(TEST-LIFECYCLE: CONTRACT, 28 тестов), плюс правки существующих наборов.

Покрытие §3 ТЗ:

1. `/meme` + 1/10/50 новых сообщений во время генерации → один мем, одна
   генерация, без `publication_stale` (параметризовано).
2. Авто-мем с теми же 1/10/50 сообщениями → публикуется (параметризовано);
   отдельно — настоящая коллизия (до генерации и гонка после неё) с точным
   кодом и без отправки.
3. Отдельные коды: модуль off, инициатива off, image backend, удалённый
   источник, закрытый гейт, коллизия — все разные, `publication_stale` нет.
4. Два воркера и рестарт: ровно одна публикация, один платный вызов, квота 1,
   уникальный `provider_called` остаётся durable.
5. Ручной приоритет: `wait_for_sending` = существующий предел; чужой `claimed`
   перехватывается; успех = только изображение. **Обновлено после ревью (B3):**
   реальное ожидание слота (`test_b3_manual_waits_for_foreign_sending_then_publishes`,
   детерминированная точка синхронизации без sleeps).
6. События: цепочка/ссылки/режим/время/факт доставки, `image_ready` ≠
   `publication_sent`; исключение отправки = `delivery_unknown`.
7. Авто-потолок: пустой = авто (нет директивы, нет обрезки, prompt > 800
   проходит), фиксированный = от зарендеренного промпта, переполненный шаблон
   = ошибка до выжимки и провайдера, `image_prompt_fits` — юнит-факт.
8. API/витрина: пусто → авто (глобально и с чатовым override), save/reload,
   auto↔fixed, `null`/`0`, некорректный ввод, отсутствие поля не стирает
   сохранённое.
9. **B1 (10 инвариантов Architect):** не теряется; одна доставка; без второй
   генерации; рестарт; квота не дважды; права/модуль своими кодами; честное
   истечение; дубль невозможен; `delivery_unknown` не переотправляется; журнал
   не спамится.
10. **B2:** реальный ростер прав (юнит + отзыв после генерации), ручная
   перепроверка RBAC, обработчик передаёт реальный хук (2 вызова).
11. **B3:** чужой `sending` → ожидание → одна публикация, без второй генерации.

Мутационная проверка (временно возвращал старое поведение, затем откатывал):

- вернуть `publication_stale` по изменению окна → падают 7 тестов
  (`*_new_messages_do_not_cancel_ready_meme`, `..._topic_changed`);
- вернуть `if not budget.known: skipped(length_limit_unknown)` → падает
  `test_auto_ceiling_generates_without_invented_limit`;
- `image_prompt_fits` без проверки L → падает `image_prompt_fits_is_exact`;
- **B1:** убрать `defer_generated_meme` из ветки отказа брони → падают 11
  тестов `test_b1_*` (артефакт теряется — ровно дефект B1);
- **B2:** отключить проверку прав на обоих путях → падают
  `test_b2_rights_revoked_during_generation_blocks_direct_publication`,
  `test_b2_manual_permission_is_rechecked_before_publication`,
  `test_b2_handler_passes_real_permission_hook`;
- **B3:** вернуть отказ `publication_in_flight` в `precheck(manual=True)` →
  падает `test_b3_manual_waits_for_foreign_sending_then_publishes`
  («ручной путь не вошёл в ожидание слота»).

Результаты прогонов (Windows, `py -3 -m pytest`, без sleeps):

- `tests/test_p0_meme_publication_hotfix.py` — **47 passed** (было 28):
  +13 B1-инвариантов, +4 B2, +1 B3, +1 по вердикту «два job_id».
- 8 наборов мемов/инициативы/API (`test_initiative_coordination`,
  `test_evol014_meme_initiative`, `test_meme_pipeline_stages`,
  `test_evol014_ui`, `test_meme_pipeline_api`, `test_meme_init_diagnostics`,
  `test_p0_meme_image_only`, `test_meme_command_autodelete`) — **194 passed**.
- Совместный прогон 9 наборов (8 выше + hotfix) — **241 passed**, exit 0.
- `tests/test_webapp_api.py` + `tests/test_webapp_js_unit.py` — 203 passed,
  2 failed; оба падения (`round1021_ui_audit`: `grid: auto-fit minmax(320px,1fr)`
  и `round1024_image_module`: «вкладок 28») относятся к `web/index.html`,
  который в этой правке не менялся, — pre-existing (см. §7).
- `node tests/js/meme_ui_fields_test.js` → `MEME-UI-FIELDS-OK`;
  `node tests/js/evol_w4_diagnostics_ui_test.js` → `EVOL-W4-UI-OK`.

## 6. Что P1 не должен сломать

- `SourceSnapshot` и его durable-вид: id/числа/коды, без текстов сообщений.
- Отсутствие любой проверки «свежести переписки» перед публикацией: новые
  сообщения/реакции/`latest_message_id`/watermark не отменяют готовый мем.
- Матрицу кодов причин: `publication_stale` — только историческое значение,
  каждый реальный случай имеет свой код (см. §2).
- Порядок «дёшево → дорого»: тумблеры/бюджет/контентные проверки стоят ДО
  LLM и ДО провайдера; бронь берётся после генерации, `sending` — ровно перед
  sender.
- `manual` приоритет через существующий `wait_for_sending` и перехват чужого
  `claimed`; RBAC по-прежнему проверяет обработчик (плюс перепроверка перед
  публикацией — B2).
- Контракт доставки: успех = РОВНО одно изображение, без caption/промпта/
  второго сообщения; журнал выводов и аналитика сохраняются.
- Идемпотентность: тот же `job_id` не даёт дубля и второй генерации; неизвестный
  статус доставки не маскируется.
- Три состояния потолка (`auto`/`fixed`/ошибка) и то, что `auto` не превращается
  в `0`/`800`/`NaN`; `T` считается только production-renderer'ом.
- События в фактах терминальной строки и `delivery.events` в API — источник для
  вкладки «Публикации»/«Диагностика».
- **B1:** отложенный артефакт не выбрасывается и не перегенерируется; одна
  активная строка на чат; доставка только через существующий тик мема и через
  существующую бронь (`mark_running` CAS + `acquire` + `begin_sending`).
- **B2:** перед публикацией перепроверяются реальный ростер/права, тумблеры,
  исходный материал и гейт; intent-lifecycle зафиксирован как N/A с причиной.

## 7. Найденное попутно

- `related-nonblocking`: ярлык `publication_stale` в `web/app.js`
  (`memeSkipLabel`) всё ещё говорит «Переписка вроде устарела» — правится в P1
  вместе с перекомпоновкой карточки (сейчас код не эмитится, ярлык виден только
  на исторических строках).
- `unrelated/pre-existing`: `tests/test_webapp_js_unit.py::
  test_js_unit_round1021_ui_audit` и `::test_js_unit_round1024_image_module`
  падают на базе (ожидают разметку/число вкладок в `web/index.html`, которого в
  файле нет). К этой правке отношения не имеют.
- `related-nonblocking` (ЗАКРЫТО в этом коммите): durable-хранилище готового
  артефакта теперь есть — `task_jobs` (`kind="meme.pending_publish"`) + байты в
  `var/meme_pending/<job_id>.bin`; см. §8.
- `related-nonblocking`: `source_material_gone` срабатывает только когда не
  осталось НИ ОДНОГО исходного сообщения снапшота (частичное удаление не
  блокирует: порог — это было бы изобретённое правило). Ошибка чтения БД →
  не блокируем (готовый мем не отменяется по догадке).
- `unrelated/pre-existing (наблюдение, воспроизведено БЕЗ этого файла тестов)`:
  в совместных прогонах 8–9 файлов изредка падает ОДИН тест из
  `tests/test_initiative_coordination.py::test_t4_diagnostics_*`, каждый раз
  другой. Причина видна в логе: `op=random_state` / `random_draw_journal` →
  `ValueError: no active connection` — процесс-глобальный singleton
  `_service` (`mca_random_source.get_service`) остаётся привязан к уже закрытому
  `DatabaseService` другого теста того же файла (`get_service` не перебиндивает,
  пока `_service.db` не None). Доказательства непричастности этого диффа:
  (а) `mca_random_source`/`initiative_diagnostics` в диффе отсутствуют;
  (б) изолированный прогон файла — 6/6 зелёных;
  (в) тот же набор БЕЗ `tests/test_p0_meme_publication_hotfix.py` дал ровно такое
  же падение (`..._refuses_on_foreign_claim`, 1 failed / 193 passed);
  (г) отдельная проверка (`probe_bind.py`) показала, что дефер/доставка/закрытие
  моих `DatabaseService` singleton НЕ привязывают (`service after close: None`).
  Своя доля загрязнения всё равно закрыта: в hotfix-файле добавлен autouse
  `_release_random_source_singleton` (сброс после каждого теста). Чужой файл не
  правил — вне области P0.

## 8. Корректирующий коммит после ревью: B1 / B2 / B3

Ревью `review.md` вернуло `Needs Fixes` по трём пунктам. Все три закрыты, каждый
доказан тестом, который падает при откате фикса (мутации в §5).

### B1 — готовый авто-мем не выбрасывается (arch/deferred-publication.md)

Реализовано ровно по решению Architect:

- **Метаданные** — строка существующей `task_jobs` (v14, миграция НЕ нужна):
  `owner="meme.initiative"`, `kind="meme.pending_publish"`,
  `coalesce_key="meme:pending_publish:<chat_id>"` (unique partial v14 → одна
  активная запись на чат), `payload` — компактный JSON без текстов сообщений
  (`chat_id`, `run_id`, `created_at`, `expires_at`, `sha256`, `size`, `mime`,
  `deferred_reason/detail`, `msg_ids/msg_count/first_id/last_id/snapshot_digest`,
  `prompt_origin`, `purpose`, `mode`), `deadline_at`, `attempt`, `result_ref` —
  путь к байтам (заполняется сразу после `enqueue`, т.к. сам `enqueue` эту
  колонку не принимает; `finish` теперь передаёт `result_ref` явно, иначе
  терминальный переход стирал бы путь).
- **Байты** — `var/meme_pending/<job_id>.bin`, атомарная запись
  temp-file → `os.chmod(0600)` → `os.replace`; каталог переопределяется
  `MEME_PENDING_DIR` (прецедент `cover_style_assets.assets_dir()`, `var/` в
  `.gitignore`, деплой `git pull --ff-only` не пачкается).
- **Ретенция** = `cfg.cooldown_seconds` (существующее число, дефолт 6 ч ≥
  межтипового интервала 1800 с); `cooldown ≤ 0` не даёт «мгновенно мёртвого»
  артефакта — берётся существующий `DEFAULT_COOLDOWN_SECONDS`. Новых TTL нет.
- **Драйвер ретрая** — существующий тик мема: `on_initiative_cycle` ПЕРВЫМ
  вызывает `deliver_deferred_all` (перебирает активные записи всех чатов, не
  зависит от ротации `MAX_CHATS_PER_PASS`); нового планировщика/воркера нет.
- **Exactly-once**: стражи (тумблеры → ростер/права → исходный материал →
  publish-гейт → тихие часы) → `mark_running` CAS → `acquire` →
  `begin_sending` → sender → `_record_meme_output` + `release(published=True)` →
  `finish(completed)` → файл удалён. Отказ слота → `requeue`, файл сохранён,
  строк журнала нет. Исключение sender'а → терминал `delivery_unknown`, файла
  нет, повтора нет. `interrupted` от существующего watchdog →
  `delivery_unknown` («crash после отправки» не переотправляется).
- **Анти-перегенерация**: при активной отложенной записи авто-проход не
  генерирует (`detail="deferred_pending"`) и не пишет строк журнала.
- **Только авто**: `manual=True` не откладывает (ручной путь ждёт слот сам).
- **Новые коды только два**: `rights_revoked`, `deferred_publication_expired`
  (оба с русскими ярлыками в `initiative_observer.REASON_LABELS`). Новых имён
  событий нет — используется закрытый `MEME_EVENTS`, принадлежность отложенному
  пути видна в `detail` (`deferred|…`) и `run_id` = исходный `jid`.
- **Image-backend на поздней отправке НЕ проверяется** (байты уже есть; блокировать
  оплаченный артефакт из-за здоровья провайдера запрещено §1.2.5).

### B2 — реальная перепроверка прав перед публикацией

- `_default_rights_check(db, chat_id)` — настоящий ростер кандидатов
  (`_candidate_chat_ids`: PG `chat_profiles` / durable SQLite
  `get_smart_chat_ids`); чата нет в ростере → `rights_revoked`
  (`chat_not_in_roster`). Нечитаемый ростер/нет БД → не блокируем (доказать
  отзыв нельзя), в фактах `detail="roster_unavailable"`.
- Ручной путь: обработчик передаёт в пайплайн тот же `is_meme_admin`, что и на
  входе (`permission_check`); отказ → `rights_revoked`
  (`permission_denied`) + одно короткое сообщение «Права на отправку мема в
  этом чате отозваны.». Проверка стоит ПОСЛЕ генерации и ПЕРЕД броней, поэтому
  тест доказывает именно «права отозваны за время генерации».
- Жизненный цикл intent — **N/A с причиной в коде и в записи**:
  `facts.publish.intent_lifecycle = {"status": "n/a", "reason":
  "meme_has_no_intent_binding"}` (у мема свой `run_id` и снапшот источника, он
  не привязан к intent-записи). Синтетическая строка контекста больше не
  выдаётся за проверку. То же зафиксировано в отложенном пути.
- И прямой, и отложенный путь используют одну и ту же проверку прав/ростера.

### B3 — ручной `/meme` реально ждёт чужую отправку

- `publication_coordination.precheck(manual=True)`: при чужом `sending` больше
  НЕ отказывает (`ok=True`, диагностика `in_flight=True`,
  `waits_for_slot=True`, `detail=claim_held`), поэтому прогон доходит до
  генерации и до существующего `acquire(wait_for_sending=MANUAL_IN_FLIGHT_WAIT_SECONDS)`.
- Ожидание — существующий durable-механизм (release-event + одна повторная
  попытка), новых таймеров нет. Правка именно в
  `services/publication_coordination.py` (B3 требовал её: отказ случался на
  `precheck`, до генерации, и пайплайн не мог «дождаться»).
- Отложенный B1-путь при этом остаётся честным: ручной запрос имеет приоритет
  (`MANUAL_PRIORITY_SECONDS`), отложенная запись просто остаётся `queued`.

### Вердикт по «два разных `job_id` публикуют дважды»

Проверено на реальном коде: **это не дубль-путь, а два законных прохода.**

- У авто-мема РОВНО ОДНА точка входа — `initiative_observer._meme_phase` →
  `meme.on_initiative_cycle` (тест
  `test_single_entry_point_for_automatic_memes` сканирует AST всех
  `services/*.py` и `handlers/*.py` и требует один вызов). Она живёт внутри
  singleflight-задачи `initiative.observe`
  (`OBSERVE_COALESCE_KEY="initiative.observe:global"`,
  `services/initiative_observer.py:79-81,1039-1055`): второй проход не
  стартует, `enqueue` вернёт `job_id` уже активной задачи.
- Второй последовательный проход с новым `job_id` ограничен собственным
  кулдауном механизма и суточной квотой: `test_two_different_job_ids_are_rate_limited_not_deduped`
  показывает `cooldown_active` и НОЛЬ вызовов провайдера на втором проходе при
  дефолтном кулдауне (6 ч).
- Две публикации при двух `job_id` воспроизводятся только при
  `cooldown_seconds=0` (тестовая конфигурация) — это следствие конфигурации, а
  не отсутствие дедупликации; новая сущность дедупа не вводилась.
- Старый тест `test_two_workers_in_one_chat_publish_exactly_once` — это проверка
  РЕПЛЕЯ одного `job_id` (так и назван в комментарии), а не двух воркеров;
  переименование/уточнение оставлено на P1-чистку документации.

### Хранилище и уборка (факты)

- Схема БД: дельта ноль (`task_jobs` v14 уже есть; новый `kind` — значение
  колонки; новых таблиц/колонок/индексов нет).
- Один файл ≤ `IMAGE_MAX_BYTES` (9 MiB), одна активная запись на чат ⇒ верхняя
  граница — `9 MiB × число чатов`, фактически сотни КБ.
- Файл удаляется в КАЖДОМ терминальном переходе (completed/failed/cancelled);
  строки убирает существующий `TaskJobStore.prune` (активные не трогает).
- Откат = только код: строки после revert остаются `queued` и инертны, файлы —
  в git-ignored `var/meme_pending/`.

## 9. B4 (Re-review 2): чужая истёкшая `sending`-бронь не съедает артефакт

Дефект (нашёл ревьюер, S9): `_deliver_deferred_row` считал
`claim.recovered_delivery_unknown` терминалом «доставка неизвестна» и удалял
оплаченный файл, хотя наш мем ни разу не отправлялся.

**Выбрано: (a) — флаг как ФАКТ, а не как терминальное состояние**, плюс
атрибуция (подсказка (b)) как защитный страж:

- `recovered_delivery_unknown` в `acquire` означает: предыдущая строка брони
  была в `sending`, её TTL истёк, и мы её восстановили. Флаг описывает
  ПРЕДЫДУЩЕГО держателя, а `ClaimDecision.granted=True` — это уже НАША свежая
  аренда, и `begin_sending` остаётся единственным разрешением звать sender.
- Своя отправка отложенного мема не может совпасть с `queued`-строкой: строка
  переводится в `running` ДО `acquire`, а падение в окне отправки ловит
  существующий watchdog → `interrupted` → ветка выше даёт честный терминал
  `delivery_unknown` **без** `acquire` (регресса нет).
- Поэтому в отложенном пути флаг почти всегда описывает ЧУЖУЮ бронь. Факт
  фиксируется (`facts.publish.delivery_recovered = {holder_kind, holder_ref,
  own}`, событие `delivery_unknown` c `detail="deferred|foreign_claim"`), а
  публикация продолжается под реально выданной бронью — ровно как прямой путь
  в этом же состоянии (там тоже `delivered=unknown` фиксируется и отправка
  выполняется).
- Почему не только (b): атрибуция может быть недоступна (снимок брони не
  прочитался → пустые `holder_kind/ref`); тогда «не доказано, что это наша
  отправка» не должно означать потерю артефакта. Комбинация «факт + страж»
  сохраняет картинку в чужом случае и остаётся терминалом в собственном.
- Защита «падение после собственной отправки» усилена, а не ослаблена: если
  истёкшая `sending`-бронь принадлежит этому мему (`holder_kind ==
  meme_initiative` и `holder_ref == run_id`), исход остаётся
  `delivery_unknown`, файл удаляется, sender не вызывается, повтора нет.

**Тесты (2, оба в существующем hotfix-наборе):**

- `test_b4_foreign_expired_sending_claim_still_delivers` — сценарий ревьюера
  S9: чужая `sending`-бронь не освобождена и истекла → первый же проход
  отложенной доставки публикует мем (`published=True`, sender 1, провайдер 0
  новых), файл жил до отправки и удалён после успеха, строка `completed`,
  `spent` и бронь квоты не изменились, события содержат `delivery_unknown`
  (`detail="deferred|foreign_claim"`) и финальный `publication_sent` с
  `delivered=true`; последующие 3 прохода не отправляют ничего.
- `test_b4_own_expired_sending_claim_is_terminal_without_resend` — обратная
  сторона: своя истёкшая `sending`-бронь (`holder_ref == run_id`) → терминал
  `delivery_unknown`, sender 0, файл удалён, повтора нет,
  `delivery_recovered.own = true`.

**Мутация:** вернуть `recovered_delivery_unknown` в безусловный терминал (как в
`46edd36e`) → красный `test_b4_foreign_expired_sending_claim_still_delivers`
(1 failed / 13 passed среди b1+b4; собственный страж-тест при этом остаётся
зелёным, что и доказывает, что менялся только «чужой» исход).

**Прогоны после B4:** `tests/test_p0_meme_publication_hotfix.py` — **49
passed**; 9 наборов мемов/инициативы/API — **203 passed**; совместно —
**252 passed, exit 0**; JS-гейты зелёные. Пре-существующие падения
(`round1021_ui_audit`, `round1024_image_module`) не тронуты, классификация
та же; наблюдение по `test_t4_diagnostics_*` (глобальный singleton
`mca_random_source._service`, чужой модуль) — без изменений, к B4 не относится.
