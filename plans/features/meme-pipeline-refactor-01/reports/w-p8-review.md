# P8 / MEME-INIT-COORDINATION - независимое ревью (Reviewer, 03.11.2026)

Кандидат: ff35a53f (ветка feat/meme-init-coord), база 760916e8.
Основание: plans/owner_inputs/2026-11-03-initiative-independence-coordination.md
(OI-2026-11-03-INITIATIVE-INDEPENDENCE), arch/initiative-coordination.md (frozen),
36 строк карты в слайсе MEME-INIT-COORDINATION.

ВЕРДИКТ: Needs Fixes. Поведение в живом контуре корректно и подтверждено
независимо, но два пункта обязательной приёмки не имеют либо работающего
покрытия, либо честной границы объёма (блокеры B1 и B2).

---

## 1. Чек-лист владельца (пункты "Инженерной трактовки")

### 1) Независимость планирования - PROVEN
Свои расписания, триггеры, вероятности, кулдауны, квоты, статистика;
срабатывание одного не запускает и не сбрасывает другое.

- V1 (свой ростер): services/meme_initiative.py:310-364.
- V2 (раздельные try): services/initiative_observer.py:1407-1421.
- V4 (чат-гейт): initiative_observer.py:1468 -> meme_initiative.py:1442-1446.
- V3/V5 закрываются журналом и интервалом (пункты 3 и 4 ниже).
- V6 (асимметрия бюджета LLM) дефектом не является и не менялся.

Тесты: test_meme_flags_never_touch_text_mechanism,
test_disabling_memes_leaves_text_phase_running,
test_text_phase_failure_does_not_cancel_meme_phase,
test_own_quotas_do_not_cross_limit,
test_meme_roster_is_independent_of_text_scan, test_chat_scope_stops_memes.
Плюс мои пробы P3.a-d: ростер и чат-гейт реально пробрасываются из мем-фазы.
Общего helper-сброса нет: мем пишет payload["meme"]/meme_chats, текст -
chats/counters; _load_payload переносит meme_chats отдельно
(initiative_observer.py:1313-1330), поэтому текстовый лимит CHATS_TRACKED_MAX
больше не вытесняет чат мема.

### 2) Случайность: один сервис, независимые draw - PROVEN
- Один клиент: services/mca_random_source.py:91-96 и :112-115 (purpose
  initiative_trigger санкционирован и не входит в карту exploration).
- Один формат трассировки: initiative_observer.py:620-676; мем идёт тем же
  контуром (meme_initiative.py:1174-1212), второго клиента/генератора нет
  (grep: ни import random, ни второго draw-клиента).
- Старое поведение "fallback_reason = отказ" удалено (meme_initiative.py:1183-1205).
  Изменённый кейс c в tests/test_evol014_meme_initiative.py:241-259 теперь ждёт
  публикацию с source=pseudorandom, fallback_reason=provider_unavailable,
  hit=True; кейсы a и b остаются random_unavailable.
- Реальный PRNG-путь: test_real_random_source_reports_actual_source
  (source=pseudorandom, provider=prng, source_impl=prng, fallback_reason=None).

### 3) Атомарная ровно одна публикация - PROVEN
- CAS-UPSERT: services/publication_coordination.py:144-184; право звать sender
  даёт только переход claimed->sending (:187-194).
- Тесты: 8 воркеров (потоки, реальный файл), оба порядка одновременной
  готовности, рестарт, TTL, устаревание окна.
- Мои пробы (не из набора Builder):
  P5.a-d: 8 одновременных корутин asyncio.gather на одном файле -> ровно одна
  бронь, ровно один sending, 7 честных publication_conflict, деградаций 0.
  P7.a-e: бронь sending с истёкшим TTL (рестарт) -> проход публикует одно
  свежее сообщение, мёртвая бронь повторить отправку не может
  (publication_expired), recovered_delivery_unknown=True и
  detail=delivery_unknown видны в фактах, другой тип затем уважает интервал.
  A1-A6 (сквозной цикл реальным кодом и реальным журналом): реальная текстовая
  публикация -> мем через 60 с блокируется publication_conflict /
  cross_type_interval и sender не вызван; через 1801 с публикуется; обратный
  порядок (реальный мем -> текст через 60 с) - текст не публикует.
- Устаревшее не отправляется: перепроверка watermark окна
  (meme_initiative.py:1572 и 1747-1760), тест
  test_stale_meme_is_not_sent_after_delay.
- Особенность, замороженная Архитектором (R4): сам восстанавливающий acquire
  проходит без проверки интервала (WHERE видит ещё старую строку), а
  last_publish_ts=claimed_at пишется в том же стейтменте. Это ровно текст
  arch/initiative-coordination.md R4, не дефект.

### 4) Межтиповой интервал - PROVEN
- Ключ initiative.cross_type_publication_interval_seconds, дефолт - существующая
  MIN_GAP_FLOOR_SECONDS = 1800 (publication_coordination.py:349-367), резолв
  chat -> hot -> дефолт.
- 0 выключает проверку интервала (:178); свой тип интервалом не ограничен
  (:180-183).
- "Не укорачивает кулдаун" обеспечено структурно: собственный кулдаун - это
  отдельный гейт механизма, интервал - отдельное условие брони, поэтому
  фактический зазор равен максимуму. resolve_gap_seconds - справочная формула
  для диагностики, не подмена гейтов.
- Тесты: test_cross_type_interval_default_and_bounds,
  test_interval_never_shortens_own_cooldown,
  test_zero_interval_disables_interval_coordination,
  test_small_interval_does_not_override_own_cooldown.
- Моя проба P4.a-c (журнала нет, интервал считается по watermark строки):
  60 с после публикации другого типа - блок cross_type_interval, 1801 с - проход,
  свой тип не ограничен.

### 5) /meme приоритетен - PROVEN (поведение), но без durable-теста
- Маркер до генерации: handlers/meme_command.py:220-229 (порядок
  delete -> priority -> pipeline), test_command_marks_priority_before_generation.
- Запрет авто-пути переходить в sending при живом маркере:
  publication_coordination.py:192-193.
- RBAC не тронут (meme_command.py:211-218); текстов ошибок добавлены, права те же.
- Мои пробы: P1.b (бронь взята авто-путём, затем появился маркер ->
  begin_sending отказывает, detail=manual_priority); P2.b-d (/meme забирает
  чужой claimed, старая бронь текста не отправляет - publication_expired,
  освобождение проигравшего не стирает бронь победителя, ручной может отправить).
- Чужой sending -> честный publication_in_flight без второй публикации:
  test_foreign_sending_yields_publication_in_flight.
- НО: мутация M4 (удаление предиката маркера из claimed->sending) не роняет ни
  один тест. См. блокер B1.

### 6) Публикации в разных чатах - PROVEN
PK chat_id, глобальной блокировки нет. test_different_chats_proceed_independently,
grep по asyncio.Lock/_GLOBAL_LOCK, моя проба P6.a-b: два реальных мем-прохода в
двух чатах публикуются, у каждого своя строка брони.

### 7) Диагностика - PROVEN (с замечанием N2)
- Текст: _note_decision (initiative_observer.py:1207-1252); chat_block_state
  получил гейт publication (:2589-2616) и поля next_eval_ts, publication,
  last_decision, random, cooldown_seconds.
- Мем: _note_state (meme_initiative.py:1960-2030) и
  availability()["diagnostics"] (:2177-2248).
- Новых таблиц диагностики нет (test_no_new_scheduler_or_lock_in_package).
- Моя проба по реальной БД: 15 гейтов текста включая publication; при отсутствии
  данных last_decision и random равны {} (не нули); publication отдаёт явные
  null и coordination=ok/degraded.
- Замечание N2: у мема last_check_ts=0 при "никогда не проверяли" (см. раздел 4).

### 8) Схема v41 - PROVEN
- _SCHEMA_VERSION_PUBLISH_CLAIM=41 и шаг chat_publish_claim_v41
  (services/database.py:3003-3013); шаг применяет pub.CLAIM_DDL_SQLITE
  (:3398-3417), второй копии DDL нет (test_v41_step_registered_and_ddl_owned_by_module).
- PG не тронут: таблицы нет в pg_db.DDL_STATEMENTS.
- Свежая БД доезжает до 41, рестарт - no-op, данные не теряются
  (tests/test_evol014_meme_initiative.py:978-1080).
- Пины 40 -> 41 в двух чужих файлах (test_evol016_prompt_journal_v39.py,
  test_mca17c_invariants_round1047.py) - только числа версии, проверил diff.

### 9) Запрещённые паттерны - PROVEN
grep по изменённым модулям и тестам: нет asyncio.sleep, time.sleep,
asyncio.Lock, create_task, import random; test_no_new_scheduler_or_lock_in_package.
Тайминги координации - настройка; TTL аренды 90/120/600 заморожены Архитектором
(раздел 3.3 arch), это не "паузы".

---

## 2. Мутации (6, проверил сам: 3 убиты, 3 выжили)

- M1 убрать claim_id из предиката claimed->sending: УБИТА
  (test_restart_reclaims_expired_claim_without_second_publication).
- M2 убрать проверку интервала из CAS-UPSERT: УБИТА
  (test_simultaneous_readiness_publishes_exactly_once, оба порядка).
- M3 убрать перепроверку свежести окна у мема: УБИТА
  (test_stale_meme_is_not_sent_after_delay).
- M4 убрать предикат manual_priority_until из claimed->sending: ВЫЖИЛА (45/45).
- M5 вернуть ростер мем-фазы к payload["chats"] (регресс V1): ВЫЖИЛА (45/45).
- M6 перестать передавать chat_enabled из фазы (регресс V4): ВЫЖИЛА (45/45).

M4, M5, M6 - ровно те обязательные контракты, которые владелец назвал поимённо
(приоритет /meme, независимость планирования, тумблер чата). В кандидате
поведение корректно (доказано пробами P1/P2/P3), но защиты от регресса нет.
---

## 3. Блокеры

### B1. Три обязательных контракта без теста, способного упасть (Builder, только тесты)
Требования: пункт 5 владельца ("автоматический пост откладывается или
отменяется"), V1 (свой ростер), V4 и SET-CHAT-TOGGLE (initiative.enabled=false
реально останавливает мемы).

Что наблюдается: мутации M4/M5/M6 не роняют ни один тест. В
tests/test_initiative_coordination.py проверяются функция ростера и
consider_chat(chat_enabled=...), но не проводка в
initiative_observer._meme_phase:1458-1470; нигде не проверен переход
claimed->sending при уже стоящем маркере.

Почему важно: окно "авто-бронь взята -> /meme поставил маркер" в реальности
большое (генерация текста идёт десятки секунд), и именно этот предикат не даёт
авто-реплике выйти сразу после ручного запроса.

Минимальное исправление (Builder, без правок продуктового кода):
1. acquire(auto) -> claim_manual_priority() -> begin_sending(claim_id) даёт
   granted=False и detail=manual_priority;
2. _meme_phase с подменённым meme.on_initiative_cycle и
   meme.meme_chat_roster -> [-100] при payload["chats"]={"-200": {}} даёт в
   вызове chat_ids=[-100] и roster_source="roster";
3. _meme_phase пробрасывает чат-гейт: chat_enabled(-777) is False, либо мем для
   выключенного чата получает initiative_disabled.

Проверка после фикса: три теста зелёные, и повтор M4/M5/M6 обязан ломать
соответствующий тест.

### B2. Третий путь отправки текстовой инициативы вне координации (Architect/PM + Builder)
Требование: "оба механизма обязаны учитывать недавние публикации ... НЕ должны
публиковаться одновременно или непосредственно друг за другом" (строка карты
MEME-IIC-PRESEND-RECENT-CHECK).

Что наблюдается: services/nostalgia_worker.py:1023-1050 делегирует готовый текст
в handle_initiative без publish_guard (:1093-1095), а при выключенных K1/K3
отправляет напрямую bot.send_message (:1051-1054) - без брони и без записи в
журнал выводов. Продукт сам считает nostalgia частью единого входа инициативы
("второго контура/пути отправки нет", T-5038). Итог: мем после nostalgia ждёт
интервал (журнал видит её как initiative_reply), а nostalgia после мема - нет.
Возможна ровно та спам-пара, которую владелец запретил, и возможна
одновременность с чужим sending.

Масштаб: memory.nostalgia_enabled = OFF в каноне (module_registry.py:403), путь
спящий. Поэтому это не дефект живого контура, но и не посторонний мусор: это
единственный оставшийся некоординированный путь отправки того же механизма.

Минимальное исправление (одно из двух):
а) Builder: в _delegate_initiative взять и освободить ту же бронь и передать
   publish_guard= (копия блока initiative_observer.py:2264-2330, около 15 строк)
   плюс тест "nostalgia не публикует сразу после мема";
б) Архитектор: явно записать в arch/initiative-coordination.md, что
   nostalgia-триггер вне объёма координации, и тогда сузить формулировку строки
   MEME-IIC-PRESEND-RECENT-CHECK, а не отмечать её VERIFIED как есть.

Проверка после фикса: тест "реальный мем опубликован -> проход nostalgia через
_delegate_initiative не отправляет (publication_conflict)" либо записанное
решение Архитектора со ссылкой.

### B3. Учётная часть (PM/Orchestrator, не реализация)
36 строк слайса MEME-INIT-COORDINATION все PENDING с evidence: [];
owner_inputs OI-2026-11-03-INITIATIVE-INDEPENDENCE имеет reconciled=false.
requirements_gate.py check --stage review --slice MEME-INIT-COORDINATION
--candidate ff35a53f даёт FAIL (37 ошибок, все - mandatory PENDING). Это
привязка доказательств, а не новый цикл разработки: после B1/B2 PM переносит
ссылки из этого отчёта в строки, добавляет пин MEME-INIT-COORDINATION в
slice_candidate_pins и закрывает input.
---

## 4. Неблокирующие наблюдения (в бэклог, без расширения слайса)

N1. Блокирующие синхронные записи SQLite в event loop - риск pre-existing, не P8.
Два одновременных мем-прохода в одном процессе на одном DatabaseService дают
sqlite3.OperationalError: database is locked: бронь отказывает fail-closed
(coordination=degraded, WARN, publication_conflict/claim_held), одно окно
потеряло публикацию, прогон занял 44 с. Проверил отдельно: то же самое
воспроизводится на коде v40 без всякой координации - синхронная запись журнала
квоты падает за 5.5 с, если главное aiosqlite-соединение держит открытую
транзакцию. В бою проход последователен по чатам, поэтому риск только при
наложении /meme и планового прохода. Дублей не создаёт. Кандидат на отдельную
задачу "не блокировать loop", текущий слайс не расширять.

N2. last_check_ts=0 у мема при "никогда не проверяли"
(meme_initiative.py:2186). P9 обязан трактовать 0 как "нет данных", а не
печатать 1970-01-01.

N3. Отклонение от замороженного раздела 6 arch: обещанное "ждём in-process
событие и одна повторная попытка" не подключено - wait_for_sending никем не
передаётся (дефолт 0.0), MANUAL_IN_FLIGHT_WAIT_SECONDS не используется.
При чужом sending поведение = сразу честный publication_in_flight (владельцу
сообщение, второй публикации нет). Требование владельца выполнено, деталь arch
нет: либо убрать мёртвый код, либо записать отклонение.

N4. meme_chat_roster: срез candidates[:ROSTER_SCAN_MAX] (32) делается ДО фильтра
"групповой + включённый", поэтому при более чем 32 чатах включённые чаты за
границей среза не рассматриваются. Для 1-2 чатов владельца не влияет.

N5. Один невоспроизведённый флейк: в одном из трёх широких прогонов
(-k "initiative or meme or publication or claim or direct_chat or direct_output",
836 тестов) упал test_text_publish_guard_cancels_without_send с
ValueError: no active connection; 8 последующих прогонов (включая 2 полных
широких и 4 повтора с соседним файлом) зелёные. Причина не локализована; в
больших прогонах видны предупреждения "closed 24-25 leaked aiosqlite
connection(s)". На поведение фичи не влияет, но это хрупкость тестового
окружения.

---

## 5. Что должен потреблять P9 (уточнения к отчёту Builder, раздел 7)

1. Блоки механизмов независимы: payload["meme"]["chats"] и
   payload["chats"][...]["last_decision"] - разные источники, не сводить.
2. "Нет данных": random == {}, last_decision == {}, publication.available is
   False либо coordination == "degraded" - это не нули; last_check_ts == 0 у
   мема значит "никогда".
3. publication - единственный источник правды о конфликте: ok, reason, detail,
   state, holder_kind, other_kind, other_age_seconds, interval_seconds,
   manual_priority_until, coordination. При coordination="degraded" интервал и
   бронь не действовали, метка в UI обязательна.
4. random.source/provider/source_impl/fallback_reason - фактический источник;
   reason="probability_one" значит "draw не выполнялся", а не "quantum".
5. Коды причин мема и текста различаются (no_random_hit против random_miss);
   ярлыки брать через общий reason_label.
6. TTL брони (90/120/600) не показывать как кулдаун механизма: это аренда
   отправки.
---

## 6. Три опоры приёмки (для этого кандидата)

Implementation: прочитаны реальные пути - CAS-UPSERT и предикат claimed->sending
(publication_coordination.py:144-194), забор и освобождение брони в тексте
(initiative_observer.py:2264-2330) и в меме (meme_initiative.py:1699-1812),
маркер /meme (handlers/meme_command.py:220-229), шов publish_guard
(direct_chat_service.py:13183-13207), миграция v41
(database.py:3003-3013 и :3398-3417), ростер и диагностика. Контракт "ровно одна
публикация, второй не отправляет, устаревшее не уходит" проверен и по коду, и
исполнением.

Test validity: прочитаны тела и утверждения (не имена) 45 тестов. Реальные файлы
SQLite, реальный DatabaseService, реальный handle_initiative с подменой только
внешних швов (send_text, writer, sender, image_provider), проверки по claim_id и
по факту вызова sender; вакуумных assert True и моков предмета проверки нет.
Ограничение: три обязательных контракта не покрыты (B1, доказано выжившими
мутациями M4/M5/M6). Статические проверки через inspect.getsource в наборе есть,
но как вспомогательные: ключевые выводы опираются на поведение.

Independent challenge: свои сценарии, не из набора Builder. P1 - маркер появился
ПОСЛЕ взятой авто-брони (авто не уходит в sending, manual_priority); P2 - /meme
забирает claimed, проигравший не отправляет и не стирает чужую бронь; P3 -
проводка фазы (ростер и чат-гейт); P4 - интервал по watermark строки без журнала;
P5 - 8 корутин asyncio.gather (ровно один sending); P6 - два чата; P7 - рестарт
с зависшей sending (delivery_unknown, без дубля); A1-A6 - сквозной цикл "реальный
текст и реальный мем" в обе стороны через реальный журнал. Все 28 утверждений
прошли. Плюс 6 мутаций: 3 убиты, 3 выжили (см. B1).

## 7. Прогоны

Кандидат ff35a53f: tests/test_initiative_coordination.py (45),
test_evol014_meme_initiative.py, test_asap8_v63_b01_initiative_observer.py,
test_asap8_f6_initiative.py, test_p0_initfix_initiative_observer.py,
test_soul1_w5_initiative_vitality.py, test_meme_command_autodelete.py,
test_meme_pipeline_api.py, test_meme_pipeline_stages.py, test_p0_meme_image_only.py,
test_evol016_prompt_journal_v39.py, test_mca17c_invariants_round1047.py,
test_database.py - 320 passed, 0 failed. Широкий прогон по ключевым словам -
836 passed (2 из 3 прогонов; один дал флейк N5). Падений, требующих классификации
на базе 760916e8, в затронутых наборах нет.

Приёмочные пробы: WorkspaceData/runs/c742e4de9e92c489/
meme-pipeline-refactor-01-revi-10676e8ec5e5/temp-c2c74cc7ce/p8probe*.py -
временные, удалить при закрытии эпика.

---

## 8. Приёмочный лист

- VERIFIED (поведение, по этому кандидату): 35 строк слайса из 36, включая
  все пункты чек-листа владельца 1-9 (с оговорками B1 по durable-покрытию
  пунктов 5/V1/V4 и N2 по диагностике).
- НЕ ПОДТВЕРЖДЕНО полностью: MEME-IIC-PRESEND-RECENT-CHECK (B2).
- Строки карты остаются PENDING до привязки доказательств силами PM (B3).
- Пункты B1 и B2 - владельцы Builder (тесты) и Architect/PM (граница объёма
  либо проводка nostalgia); B3 - PM/Orchestrator.

---

# Re-review 2 (Reviewer, 03.11.2026): B1/B2 закрыты

Кандидат: f9d1cda9 (ветка feat/meme-init-coord), база 760916e8.
Проверялись только блокеры прошлого круга (B1, B2), деградация и отсутствие
регресса по чек-листу; неизменённые механизмы заново не перепроверялись.

**Итог: B1 закрыт, B2 закрыт. Вердикт: Approved (поведение и покрытие).**
Учётная привязка строк за PM (раздел 6), это не новый цикл разработки.

## 1. B1: три гарантии теперь защищены тестами

tests/test_initiative_coordination.py, +3 теста (45 -> 48 -> 59 вместе с B2):

1. test_automatic_path_cannot_begin_sending_after_manual_priority:
   acquire(auto) -> claim_manual_priority() -> begin_sending(auto) даёт
   granted=False, reason=publication_conflict, detail=manual_priority, строка
   остаётся claimed с прежним claim_id; ручной acquire(manual=True) забирает
   бронь и проходит в sending; авто-бронь после этого отправить не может.
2. test_meme_phase_roster_comes_from_own_source: реальный _meme_phase при
   payload["chats"] = {другой чат} спрашивает meme.meme_chat_roster ровно раз,
   передаёт [CHAT], пишет roster_source="roster", separate_from_initiative=True.
3. test_meme_phase_passes_chat_gate_to_meme: гейт передан callable, для
   выключенного чата даёт False, реальный on_initiative_cycle -> consider_chat
   возвращает initiative_disabled, published=False (видно и в payload["meme_chats"]).

Мои мутации (не из отчёта Builder; правки откатывались git checkout, дерево
после прогонов чистое):
- M4 убрать предикат manual_priority_until из claimed -> sending (AND 1 = 1):
  FAILED test_automatic_path_cannot_begin_sending...: assert True is False
  (granted=True, state='sending').
- M5 вернуть ростер фазы к payload["chats"]: FAILED оба теста фазы
  (roster_calls=0, chat_ids=[]).
- M6 убрать chat_enabled=chat_observer_enabled: FAILED
  test_meme_phase_passes_chat_gate_to_meme (callable(None) is False).

Все три убиты; в первом круге ровно эти мутации выживали (45/45).

## 2. B2: координация на всех вызовах handle_initiative

Шов: publication_coordination.TextPublication / open_text_publication
(precheck -> acquire -> guard -> release). Точки: наблюдатель-повод (было),
делегированный кандидат nostalgia (nostalgia_worker:1120-1154), legacy-отправка
nostalgia (:1055-1096), heartbeat (memory_maintenance:587-620), диагностика
(initiative_diagnostics:1054-1072). Вызовов шва в продакшене ровно 4, все с
publish_guard. Сигнатура handle_initiative не менялась: AST ff35a53f vs
f9d1cda9 идентичен, publish_guard последний kw-only, default None
(direct_chat_service.py:12819-12824).

Мои пробы (свои сценарии, реальный код обеих сторон, реальный SQLite, время
параметром; временные скрипты в WorkspaceData/runs/c742e4de9e92c489/
meme-pipeline-refactor-01-b412c6be39fc/temp-1aa94452f9):

- G1 "мем после nostalgia" (реальный мем-код): реальная legacy-отправка
  nostalgia (sent=1), затем сразу реальный meme.consider_chat: published=False,
  reason=publication_conflict, detail=cross_type_interval.
- G2 "nostalgia после мема" (реальный мем-код): реальный мем публикует
  (watermark last_publish_kind=meme_initiative), затем nostalgia через 60 с:
  sent=0, bot.calls=[], skipped=1; через 1801 с: sent=1, ровно одно сообщение.
  Постоянной блокировки после первой пары нет.
- A (строка брони, без мема): текстовая публикация, мем через 60 с отказан
  cross_type_interval (other_kind=initiative_reply), через 1801 с разрешён.
- C (heartbeat против живого маркера /meme): тик при маркере 600 с: sent=[],
  intent остаётся pending, attempts=0, worker_budget.consume НЕ вызван; после
  истечения маркера ровно одна отправка, watermark released/initiative_reply,
  бюджет ровно по одному вызову на scope.
- D (деградация без таблицы): open_text_publication даёт
  coordination="degraded", granted=True; реальный heartbeat-тик публикует
  (sent=1). Для nostalgia то же покрыто
  test_t1_degraded_without_claim_table_still_sends.
- E (структурная защита end-to-end): добавил в services/ настоящий новый модуль
  с вызовом handle_initiative без publish_guard, T5 FAILED
  (services/_p8r2_unguarded_probe.py:6); модуль удалён, T5 снова зелёный.
  Проверка падает на реальной новой точке, а не только на своём helper.

Тела новых тестов прочитаны: утверждают наблюдаемое (состояние строки брони В
МОМЕНТ отправки, факт вызова/невызова sender, статус и attempts intent,
потраченность бюджета, watermark), подменяют только внешние швы (send_text, bot,
ростер, settings loader); моков предмета проверки нет.

## 3. Неблокирующие наблюдения (в бэклог, слайс не расширять)

D1. Диагностика, dry-run: arch §10.3 заморозил "use_mock -> publish_guard=None",
а кандидат передаёт publication.guard и в mock-режиме
(initiative_diagnostics:1054-1064). Наблюдаемо (проба E): при живой чужой брони
dry-run отдаёт status=cancelled/publication_conflict(claim_held) и не показывает
текст, хотя ничего не публикует и бронь не занимает (claim=False); то же в
30-минутном интервале после мема. Состояние чата не портится, вывод честный, но
это изменение поведения админской проверки и отклонение от замороженного
текста. Правка, если Архитектор хочет буквально по arch:
publish_guard=(None if use_mock else publication.guard). Решение Architect/PM:
принять отклонение в arch §10.3 либо выровнять код. Блокером не считаю:
требование владельца не затронуто, состояние не искажается.
D2. Реальный режим диагностики не ставит маркер manual_priority_until
(arch §10.3: "как manual"). Спам-риска нет, бронь берётся ДО генерации, поэтому
авто-путь уже не пройдёт; отличие только в трактовке одновременного /meme.
D3. У nostalgia нет дешёвого precheck перед генерацией (arch §10.3 хотел precheck
после кулдауна): координация срабатывает после LLM, отказ только не отправляет.
Цена: потраченный LLM-вызов на конфликт, публикации нет.
D4. Legacy-отправка nostalgia по-прежнему не пишет журнал выводов
(mca_bot_outputs), Builder зафиксировал. Для пары не важно (интервал берётся из
строки брони, проверено G2/A), но общий антифлуд и min_gap текстовой инициативы
эту отправку не видят. Pre-existing, слайс не расширяет.
D5. T5 ловит вызовы по ИМЕНИ (handle_initiative, initiative_entry). Новый путь
отправки МИМО шва (как legacy nostalgia через bot.send_message) или вызов через
алиас/getattr она не увидит. Проверка ровно такая, как заказано arch §10.3;
ограничение стоит записать как остаточный риск, чтобы "структурная защита" не
читалась шире, чем есть.
D6. N1 прошлого круга (синхронные записи SQLite в event loop) получил больше
точек: бронь берут ещё heartbeat, nostalgia (2) и диагностика. Характер риска тот
же (busy_timeout 5 с, fail-closed), новых дублей нет. Отдельная задача.
D7. Флейк nostalgia-наборов воспроизведён на БАЗЕ до P8 (760916e8): 2 падения из
4 прогонов набора из 7 файлов; на кандидате 1 из 3. Сигнатура одна:
ValueError: no active connection и [random_source] prng journal failed (запись
фонового refill в закрытое соединение), падающий тест каждый раз разный
(test_say_verdict_posts_replica, test_d14_..., test_d06_...). К кандидату
отношения не имеет; в бэклог: изолировать фоновые задачи random_source между
тестами.

## 4. Прогоны (кандидат f9d1cda9)

- tests/test_initiative_coordination.py: 59 passed.
- nostalgia (test_nostalgia_worker, test_nostalgia_w2,
  test_p0_followup_nostalgia_ab, test_asap5_integration_w3): 138 passed.
- тот же набор 7 файлов, что у Builder: 170 passed (2 прогона), 1 флейк D7.
- meme (test_evol014_meme_initiative, test_meme_command_autodelete,
  test_meme_pipeline_api, test_meme_pipeline_stages, test_p0_meme_image_only):
  99 passed.
- initiative/observer (test_asap8_f6_initiative, test_asap8_v63_b01_...,
  test_asap8_v6_c06a_heartbeat, test_initiative_delivery_telemetry,
  test_p0_initfix_..., test_soul1_w5_initiative_vitality,
  test_soul1_w5_observer_gates): 98 passed.
- пины версии (test_evol016_prompt_journal_v39, test_mca17c_invariants_round1047):
  14 passed.
- широкий прогон -k "initiative or meme or publication or claim or direct_chat or
  direct_output or nostalgia or heartbeat": 1121 passed.

## 5. Три опоры приёмки (этот кандидат)

Implementation: прочитаны реальные пути: TextPublication/open_text_publication,
все 5 точек отправки текста, guard в handle_initiative
(direct_chat_service:13183-13207, до первого сетевого вызова), предикат
claimed->sending (publication_coordination:193-200), release с watermark
(:202-214), брокерство мема (meme_initiative:1481-1501). Контракт "в паре ровно
одна публикация, вторая сторона откладывается и потом не блокируется навсегда"
подтверждён и кодом, и исполнением.

Test validity: прочитаны тела и утверждения новых B1/B2 тестов; они проверяют
состояние брони в момент отправки, факт вызова sender, статус и attempts intent,
потраченность бюджета, watermark; подменяются только внешние швы; T5 имеет
самопроверку (>=4 реальных точки) и фальсификацию. Ни одна из трёх гарантий B1
больше не выживает при удалении (M4/M5/M6 убиты), каждая точка B2 ломает свой
тест при удалении publish_guard (M7/M8 убиты, новая точка в services/ ломает T5).

Independent challenge: сценарии, которых нет в наборе Builder: живой маркер
/meme против heartbeat (C), деградация без таблицы для heartbeat (D), реальный
мем и реальная nostalgia в обе стороны (G1/G2), сквозная проверка T5 на
настоящем новом модуле (E). 30 утверждений в пробах, все прошли; 6 мутаций, все
убиты.

## 6. Что должен сделать PM (учётная часть, не новый цикл разработки)

1. Привязать 36 строк слайса MEME-INIT-COORDINATION к доказательствам этого и
   прошлого отчёта; пин slice_candidate_pins["MEME-INIT-COORDINATION"] =
   f9d1cda9 (или финальный SHA, если последуют правки D1/D2).
2. Добавить обязательную по arch §10.5 строку MEME-IIC-TEXT-CALLSITES-COORDINATED
   (все отправляющие вызовы шва держат бронь плюс структурная проверка), сейчас
   её в карте нет.
3. Расширить write_scope слайса: services/nostalgia_worker.py,
   services/memory_maintenance.py, services/initiative_diagnostics.py,
   tests/test_nostalgia_worker.py (arch §10.5), сейчас в slice-graph.json их нет.
4. Закрыть owner_inputs OI-2026-11-03-INITIATIVE-INDEPENDENCE (reconciled=false).
5. После привязки: check --stage review --slice MEME-INIT-COORDINATION
   --candidate f9d1cda9.

Живая приёмка после релиза (PET_PROJECT): /meme в чате владельца и отсутствие
инициативной реплики/heartbeat-текста в пределах интервала остаётся за релизной
проверкой; независимое ревью она не блокирует.
