**P9 - MEME-INIT-DIAG: независимое ревью (сервисная диагностика по механизмам)**

Ревьюер: независимая проверка (не Builder).
Кандидат: **6d09347b306e801c477fd46e79527b74841a067d** (`feat/meme-init-diag`), база
**a43e366e0835f0b6b9d243509fa9be9c1affbda0** (merge P8).
Слайс: `MEME-INIT-DIAG`, строки `MEME-IIC-DIAG-TIMES` / `-RANDOM` / `-COOLDOWN-CONFLICT` /
`-NO-MIX` (`strict_evidence: true`, `live_required: false`). Строка `MEME-IIC-DIAG-UI` - это P4,
вне этой полосы.
Изменено ровно три файла, только добавления: `services/initiative_diagnostics.py` (+718),
`tests/test_meme_init_diagnostics.py` (+768), отчёт Builder (+201). Схема, события, `web/**`,
`handlers/**`, `meme_initiative.py`, `initiative_observer.py` не тронуты.

**Вердикт: Needs Fixes.** Поведение в основном честное, но два реальных состояния дают ложные
показания, которые P4 отрисует как есть: не отражены два настоящих гейта мем-механизма (тумблер
инициативы в чате и отсутствие таблицы брони), и "время следующей проверки" текста может оказаться
в прошлом. PM **не связывает** строки P9 до исправления.

**1. Три опоры (что именно проверено)**

**Implementation.** Прочитаны обе сборки блока (`text_mechanism_diagnostics` :1467-1567,
`meme_mechanism_diagnostics` :1606-1785, `collect_mechanism_diagnostics` :1788-1883) и их реальные
источники: `initiative_observer.chat_block_state` (:2474-2697: `state.next_eval_ts`,
`last_eval_age_seconds`, `last_initiative_output_age_seconds`, `sent_in_window`, `effective.*`,
`items`), `meme_initiative.availability` (:2339-2462) и `_note_state` (:2159-2219),
`meme.quota_view` (:1066-1097), `meme.SKIP_REASONS` (:152-162), боевой порядок гейтов
`consider_chat` (:1457-1514), `PublicationCoordinator.precheck` (:688-767) и `SqliteClaimStore.*`.
Ни один блок не читает поля другого; `output_kind` различает источники; новых таблиц и событий нет
(diff и поиск записи в новом блоке: `db.execute`/`INSERT`/`UPDATE`/`emit_` отсутствуют).

**Test validity.** Прочитаны тела и утверждения всех 14 тестов, а не имена. Тесты опираются на
реальные `DatabaseService`/SQLite, реальный `on_initiative_cycle`/`_note_decision` и реальную бронь;
подменяются только внешние швы (`sender`/`image_provider`/`random_source`/`summarizer`), предмет
проверки не мокается. Утверждения проверяют значения и состояния (null против нуля, конфликт из
брони, коды причин), а не факт вызова. Проверено мутациями (раздел 5): четыре семантических поломки
роняют целевые тесты. **Ограничение:** тесты 3 и 10-13 не покрывают два состояния из раздела 3
(тумблер чата, отсутствие таблицы брони) и не сравнивают `last_check_ts` с `next_check_ts`,
поэтому ложные показания проходят зелёными.

**Independent challenge.** Свои сценарии (не из набора Builder), на его же фикстурах: тумблер чата
выключен; отсутствует таблица брони; бронь держит текст; ровно граница кулдауна; решение "сейчас",
а оценка 2 ч назад; варианты draw (p=1, p=0, deferred, реальный draw с fallback). Скрипты временные,
в `WorkspaceData/runs/.../temp-101d6ddb17`, в поставку не входят.

**2. Честные правила: PROVEN / NOT PROVEN**

| # | Правило | Итог | Наблюдаемое доказательство |
|---|---|---|---|
| 1 | Два независимых блока, не сливаются, всегда присутствуют, наборы полей = константы | **PROVEN** | `set(block) == MECHANISM_BLOCK_FIELDS` во всех состояниях (тест 10, мои пробы, включая `chat_id=None`); у текста `stages=None`, у мема `blocking=None`; в `collect` каждый блок собирается своей функцией |
| 2 | Нет данных не равно ноль: journal 0 -> `null`; законный `remaining_seconds=0` остаётся 0 с `basis`; неизвестный лимит - `null` | **PROVEN** | тест 2; моя проба границы: `own=3600`, вызов провайдера ровно 3600 с назад -> `remaining=0`, `basis=last_provider_call`, при `+1 с` тоже 0; "никогда" -> `last_check_ts=null`, `basis_ts=null`; `limit=null` при неудачном чтении настроек |
| 3 | Деградация: `coordination="degraded"` -> блок недоступен, конфликт `null`/unknown | **PROVEN только для объекта `publication`; на уровне механизма - НЕТ** | тест 3 и проба: `publication.conflict=null`, `conflict_state=unknown`, `available=false`, `degraded=[text,meme]`. Но при отсутствии таблицы брони боевой гейт мема отказывает `schema_absent` (`detail=publish_claim_absent`), а блок отдаёт `ready=true`, `ready_reason="ok"`, `skip=null` (см. F1) |
| 4 | Конфликт - только из `publication`; записанная причина -> `skip_recorded` | **PROVEN** | тест 4; моя проба: бронь держит текст -> у мема `publication.conflict=true`, `claimed_by="initiative_reply"`, `holder_kind="meme_initiative"` (для кого спрашивали), `skip.origin="publication"`, `skip.code="publication_conflict"`; записанный в payload `publication_conflict` сам конфликт не создаёт |
| 5 | `reason="probability_one"` -> draw не выполнялся, без value/id | **PROVEN** | тест 5 и мои входы: p=1 -> `performed=false`, `hit=null`, `value=null`, `draw_id=null`, `source=null` (в сырой трассе есть `hit=true`, диагностика его честно гасит); p=0 и `deferred` тоже `no_draw`; реальный draw с `fallback_reason` -> `performed=true`, `source=pseudorandom`, `selected_source=quantum` (fallback не выдан за отказ) |
| 6 | Кулдаун - свой; TTL брони и `manual_priority_until` только в `publication` | **PROVEN** | сверен базис боевого гейта (`consider_chat` :1484-1487: `last_provider_ts` + `cfg.cooldown_seconds`) с диагностикой; тест 6; проба: 3600 с кулдауна при вызове 60 с назад -> `remaining=3540`, ни 90/120/600 не подставлены, `manual_priority_until` встречается только в `publication`; текст - `min_gap_seconds` от последней инициативной публикации |
| 7 | Причины пропуска - существующие коды и порядок реальных гейтов | **NOT PROVEN (неполный набор гейтов)** | коды зарегистрированы (`cooldown_active`, `daily_quota_reached`, `publication_conflict`, `disabled_by_setting`, `not_enough_messages` - все в `REASON_LABELS`), порядок availability -> квота -> кулдаун -> тихие часы -> бронь совпадает с `consider_chat`. Но два реальных гейта мема не отражены: тумблер `initiative.enabled` чата и наличие таблицы брони (F1) |
| 8 | Нет утечки текстов прикола/выжимки, промптов, секретов, контента | **PROVEN для наблюдаемых данных (с оговоркой)** | тест 7: "секретные" выжимка и прикол не появляются в JSON, набор ключей входит в контракт; в новом блоке нет свободного текста по построению (всё из кодов и чисел). Оговорка: `_scalar_dict` пропускает любую строку, а не только код, поэтому гарантия держится на текущих писателях (O3) |
| 9 | Только аддитивность: ни новых таблиц, ни изменения схемы сверх v41 | **PROVEN** | diff: +718/+768/+201, удалений нет; в новом блоке нет ни одной записи и ни одного события; тест 8: `analytics_snapshot` до/после - те же ключи и типы, durable payload не перезаписан |

**3. Блокеры**

**F1. Не отражены реальные гейты мем-механизма: тумблер чата и отсутствие таблицы брони.**

Требование: строка `MEME-IIC-DIAG-TIMES` - "выполненные условия и причина пропуска"; правило 7
(порядок реальных гейтов); правило 3 (деградация не выдаётся за "всё хорошо"). Поле
`conditions.initiative_enabled` названо как настройка чата `initiative.enabled`.

Воспроизведение (два состояния, оба живые):
1. Тумблер чата выключен. Реальный проход мема с `chat_enabled=lambda _cid: False`
   (`meme.on_initiative_cycle`, тот же шов, что у боевого пути) даёт
   `stage=skipped, reason="initiative_disabled"`, публикации нет. Диагностика в этом же состоянии
   (те же настройки, тот же журнал): `ready=true`, `ready_reason="ok"`, `skip=null`,
   `conditions.initiative_enabled=true`.
2. Нет таблицы брони (старая БД, деградация). Боевой гейт: `skipped, reason="schema_absent"`,
   `detail="publish_claim_absent"`. Диагностика: `ready=true`, `ready_reason="ok"`, `skip=null`,
   при этом `publication.degraded=true`, `available=false`.
3. Тот же корень: на кулдауне блок отдаёт `ready=true` **и** `skip=cooldown_active`
   (`remaining=3540`) - два поля одного блока противоречат друг другу.

Влияние: P4 покажет "мемы готовы" в чате, где мемы выключены или физически не могут публиковаться,
и "готов" рядом с собственной причиной пропуска. Это тот класс, который P8-ревью запретило.

Причина (по коду): `ready` выводится только из `availability` (`reason=="ok"`), а `availability`
знает лишь мастер-флаг (`observer_enabled()`), настройки мема, image и схему журнала квоты; тумблер
чата и наличие таблицы брони в неё не входят. `skip` для брони смотрит только `pub_view["ok"]`,
который при деградации равен `true`.

Минимальное исправление (Builder, один файл плюс тесты):
- передать в `meme.availability(...)` комбинированный признак "инициатива выключена":
  `obs.observer_enabled() and await obs.chat_observer_enabled(cid)` - параметр `initiative_on=`
  существует ровно для `SKIP_INITIATIVE_DISABLED`; тогда `reason`, `conditions.initiative_enabled`
  и `skip` (`origin="availability"`) становятся правдой без нового кода причины;
- при `publication.degraded` (таблицы брони нет) отдавать `skip=schema_absent`,
  `origin="publication"` - это фактическая причина остановки мема (`consider_chat` :1506-1507);
- вычислять `skip` раньше `ready` и сделать `ready = bool(available) and skip is None`,
  `ready_reason = skip.code` (сейчас `ready` противоречит `skip`), либо явно переименовать поле
  в "доступность по настройкам и инфраструктуре" и запретить P4 показывать его как готовность.

Перепроверка: три теста в существующем файле: (а) тумблер чата off -> `skip.code="initiative_disabled"`,
`conditions.initiative_enabled is False`, `ready is False`; (б) таблицы брони нет ->
`skip.code="schema_absent"`, `ready is False`, `publication.conflict is None`; (в) кулдаун активен ->
`ready is False` при `skip.code="cooldown_active"`.

**F2. "Время следующей проверки" текста может быть в прошлом.**

Требование: `MEME-IIC-DIAG-TIMES` - "время последней и время следующей проверки... значения берутся
из реального состояния".

Воспроизведение: payload с `last_eval_ts = now - 7200` и `last_decision.ts = now` (так пишет сам
наблюдатель на гейтах и на пропуске draw: `_note_decision` вызывается до оценки). Диагностика при
`now`: `last_check_ts = 1793707200`, `next_check_ts = 1793702700`, `next_check_basis="eval_interval"`,
то есть next на 4500 с раньше last. В P4 это буквально "следующая проверка: прошедшая дата".

Влияние: владелец видит дату в прошлом и не может понять, когда механизм реально посмотрит чат; это
само поле, ради которого заведена строка TIMES. Состояние не экзотическое: так ведёт себя любой
проход, где решение записано, а оценка не выполнялась (min_gap, антифлуд, конфликт публикаций,
дневной кап, промах draw).

Причина: `last_check_ts` из `last_decision.ts` (пишется на каждом шаге), а `next_check_ts` из
`state.next_eval_ts = last_eval_ts + eval_interval` (только оценки). Два разных базиса в одном блоке.

Минимальное исправление: считать оба поля на одном базисе. Если `last_eval + interval` раньше
`last_check_ts`, отдавать `next_check_ts=null` с `next_check_basis="every_pass"` (следующая попытка -
следующий проход), иначе - дату с `eval_interval`. Тест: два состояния (`eval` 2 ч назад при решении
"сейчас" -> `next_check_ts is None`, `basis="every_pass"`; обычное состояние -> сдвиг ровно на разницу,
как в тесте 11).

**4. Неблокирующие наблюдения (в бэклог слайса, объём P9 не расширять)**

- **O1.** `quota.remaining=0` при `limit<=0` и `unlimited=true` (текст): ноль, который означает
  "без капа", - тот же класс "ноль вместо нет данных", только в другую сторону. Тест 13 фиксирует
  такое поведение, поэтому он же и мешает исправлению. Предпочтительно `remaining=null` при `unlimited`.
- **O2.** `publication.degraded_reason` достраивается до `claim_table_absent`, если `precheck` бросил
  исключение (fallback в `chat_block_state` и `meme_mechanism_diagnostics`): другая причина подписана
  как отсутствие таблицы.
- **O3.** `_scalar_dict` пропускает любую строку. Утечки сегодня нет (писатели пишут коды и счётчики),
  но гарантия "наружу только коды" держится на писателях, а не на фильтре: короткая свободная строка
  (например, `kind`/`action` из LLM-вердикта) пройдёт, и тест 7 не покраснеет.
- **O4.** `draw_block`: при трассе без `value`, без `deferred` и с пустым `reason` получается
  `performed=true` при `value=null`. Из боевых путей недостижимо (все вызовы `build_draw_trace`
  передают код причины), но проверка `performed = not no_draw_reason` хрупкая; надёжнее требовать
  `value is not None`.
- **O5.** Для мема при отсутствии payload `next_check_ts` не учитывает продление до сброса суточной
  квоты, хотя `_note_state` пишет такое значение в payload.
- **O6.** `conditions` у двух блоков означают разное: у мема - живые флаги `availability`, у текста -
  записанные условия последнего прохода (не помечены как записанные). Для P4 стоит подписать это
  в контракте, чтобы старое не читалось как текущее.

**5. Прогоны и мутации (кандидат 6d09347b)**

| Набор | Результат |
|---|---|
| `tests/test_meme_init_diagnostics.py` | **14 passed** (5.5 с) |
| новый файл плюс `test_soul1_w5_initiative_vitality`, `test_initiative_coordination`, `test_initiative_delivery_telemetry`, `test_round1025_f8_registry` | **133 passed** (22.5 с) |
| `tests -k "meme or initiative or init_coord"` | **328 passed, 17595 deselected** (84 с), exit 0 |

Падений нет - сравнивать с базой `a43e366e` не потребовалось (классифицировать нечего).

Мутации (внешний pytest-плагин, исходники не менялись): четыре из отчёта Builder воспроизведены.

| Мутация | Упавшие тесты |
|---|---|
| кулдаун берётся из `CLAIM_TTL_SECONDS` | `never_checked...`, `cooldown_remaining_uses_mechanism_cooldown...`, `current_skip...`, `missing_chat...` (4 failed) |
| `degraded` -> `conflict=false` | `degraded_coordination_is_reported_as_degradation` (1 failed) |
| `_stamp_or_none` возвращает `0` | `two_blocks...`, `never_checked...`, `collector_never_raises...` (3 failed) |
| `draw_block` всегда `performed=true` | `probability_one_is_reported_as_no_draw` (1 failed) |

**6. Гейт и связывание строк (PM)**

`requirements_gate.py check --stage review --slice MEME-INIT-DIAG --candidate 6d09347b...` даёт
4 ошибки "mandatory PENDING" (строки ещё не связаны) и 1 "candidate mismatch": в карте
`candidate_commit` всё ещё `f9d1cda9`, пина `MEME-INIT-DIAG` нет. Это учётная часть, а не повод
к переделке, но связывать нельзя до исправления F1/F2: иначе VERIFIED будет стоять на полях,
которые в двух реальных состояниях лгут.

Порядок: Builder правит `services/initiative_diagnostics.py` плюс 4-5 тестов в существующем файле,
затем фокусная перепроверка (эти тесты и три моих сценария), затем PM связывает четыре строки на
новом кандидате, добавляет пин слайса и обновляет `candidate_commit`.

Строки `MEME-IIC-DIAG-TIMES` / `-RANDOM` / `-COOLDOWN-CONFLICT` / `-NO-MIX`: **не VERIFIED**
(TIMES - F2 и часть F1; COOLDOWN-CONFLICT - часть F1 по `ready` и деградации; RANDOM и NO-MIX
по своему содержанию доказаны, но относятся к тому же кандидату).

---

## Re-review 2 (после исправления F1/F2)
Ревьюер: та же независимая проверка. Кандидат: **53daa257** (код **ad4cf460**, ветка `feat/meme-init-diag`),
база исправления **6d09347b** (отклонённый кандидат), база слайса **a43e366e**. Слайс и строки те же:
`MEME-IIC-DIAG-TIMES / -RANDOM / -COOLDOWN-CONFLICT / -NO-MIX`.

**Вердикт: Approved.** Оба блокера закрыты и проверены своими сценариями (не набором Builder); ранее
доказанное не сломалось, регрессий в изменённых путях нет. PM может связывать четыре строки P9 на этом
кандидате (см. §6).

Изменения этого раунда: `services/initiative_diagnostics.py` (+79/-9) и `tests/test_meme_init_diagnostics.py`
(+222/-6) плюс отчёт Builder. Схема, события, `web/**`, `handlers/**`, `meme_initiative.py`,
`initiative_observer.py`, `publication_coordination.py` не тронуты; в добавленных строках нет ни одной
записи в БД и ни одного события (проверено фильтром по диффу). Весь слайс от a43e366e: четыре файла
(два продуктовых + два отчёта).

**1. Три опоры**

**Implementation.** Прочитан боевой порядок гейтов `consider_chat` (meme_initiative.py :1451-1516) и сверен
с новым порядком причины в блоке (initiative_diagnostics.py :1778-1815): availability
(инициатива/настройки/image/журнал) -> квота -> свой кулдаун -> тихие часы -> нет таблицы брони -> бронь.
`_initiative_on` (:1607-1625) спрашивает ровно ту пару, что и боевой проход (`observer_enabled()` +
`chat_observer_enabled(chat)`; прод-проход передаёт эту функцию в `chat_enabled`, initiative_observer.py
:1468). `availability(initiative_on=...)` существует и отдаёт `SKIP_INITIATIVE_DISABLED` без нового
кода причины (:2339-2389). Ветка `publication.degraded -> schema_absent` соответствует боевому
`skipped(SKIP_SCHEMA, detail="publish_claim_absent")` (:1506-1507) и не превращает деградацию в
"конфликта нет". `ready` выводится из `available AND skip is None` (:1810-1815). F2: сверка базиса
(`next <= last` -> `null`/`every_pass`, :1518-1526) стоит до отдачи полей.

**Test validity.** Прочитаны тела четырёх новых тестов, а не имена: каждый сравнивает блок с живым
проходом в том же состоянии (`live.reason == block.skip.code`), проверяет значения (`ready is False`,
`remaining_seconds=3540`, `degraded is True`, `conflict is None`, `next_check_ts is None`,
`next_check_basis="every_pass"`, `next > last`), а не факт вызова. Моки - только внешние швы
(`chat_observer_enabled`, `image_provider`, `summarizer`, `random_source`); предмет проверки
(payload/журнал/бронь/сборщик) настоящий. Тесты не пустые: четыре мутации исходника роняют ровно
целевые тесты (см. раздел 4).

**Independent challenge.** Свои фикстуры (не из набора Builder) и свои сценарии, включая два составных
состояния, которых в тестах нет: "кулдаун И нет таблицы брони" и "тумблер чата off И нет таблицы брони".
Все десять состояний сверены с живым проходом мема в том же состоянии. Скрипты временные, в
WorkspaceData/runs/.../temp-7cc8015b90, в поставку не входят.

**2. Наблюдённая матрица гейтов (живой проход рядом с блоком, одно состояние)**

| Состояние | живой проход | ready | skip.code | skip.origin | прочее |
|---|---|---|---|---|---|
| всё включено, пауз нет | publish/sent | true | null | - | ready_reason="" |
| тумблер чата off | skipped initiative_disabled | false | initiative_disabled | availability | conditions.initiative_enabled=false, available=true |
| мастер-флаг off | skipped initiative_disabled | false | initiative_disabled | availability | то же |
| мем-модуль off | skipped disabled_by_setting | false | disabled_by_setting | availability | - |
| своя пауза 3600, вызов 60 с назад | skipped cooldown_active | false | cooldown_active | cooldown | remaining=3540 |
| тихие часы 11:00-23:00 | skipped quiet_hours | false | quiet_hours | quiet_hours | - |
| квота 3/3 | skipped daily_quota_reached | false | daily_quota_reached | quota | - |
| нет таблицы брони | skipped schema_absent, detail=publish_claim_absent | false | schema_absent | publication | degraded=true, conflict=null, conflict_state=unknown |
| кулдаун И нет таблицы брони | skipped cooldown_active | false | cooldown_active | cooldown | порядок как в бою, degraded=true |
| чат off И нет таблицы брони | skipped initiative_disabled | false | initiative_disabled | availability | порядок как в бою |

Во всех десяти состояниях код причины блока совпал с кодом живого прохода (10/10). Дополнительно
проверено обратное правило: ни в одном блоке (мем и текст) нет одновременно ready=true и непустого skip.

**3. F2: время следующей проверки (свои фикстуры)**

| Состояние | last_check_ts | next_check_ts | basis |
|---|---|---|---|
| оценка 7200 с назад, решение "сейчас" | NOW (1793707200) | null | every_pass |
| обычное: оценка и решение в одном проходе | NOW-3600 | NOW-900 | eval_interval, next > last |
| ровно граница: оценка = NOW минус интервал (2700) | NOW | null | every_pass |
| next = last + 1 | NOW | NOW+1 | eval_interval, дата выдаётся |
| наблюдатель давно не работал (и оценка, и решение в прошлом) | NOW-3600 | null | every_pass |

Инвариант (next есть только вместе с last и next >= last) проверен и для мем-блока: там next пишется как
max(now, last_provider + cooldown) в _note_state, поэтому дата в прошлом структурно недостижима.
Совпадение next == last схлопывается в null (условие <=), "на единицу позже" остаётся датой: граница
ведёт себя честно, а не скрывает всё на всякий случай.

**4. Прогоны, мутации и флейк**

| Прогон | Результат |
|---|---|
| tests/test_meme_init_diagnostics.py | 18 passed (5.5 с) |
| файл + test_soul1_w5_initiative_vitality + test_initiative_coordination + test_initiative_delivery_telemetry + test_round1025_f8_registry | 137 passed (22 с) |
| tests -k "meme or initiative or init_coord" | 332 passed, 4 прогона из 5; в одном падение test_mca09_intents_block_e_round1040::test_handle_initiative_sent_single_transport_chunks (в изоляции файл зелёный: 15 passed) |
| то же на базе 6d09347b (отдельный worktree) | 328 passed, 7 прогонов из 8; в одном 2 падения: test_mismatch_chosen_reply_sent_chat_keeps_reason + test_mca09_intents_block_e_round1040::test_nostalgia_delegate_initiative_sent |

Вывод по флейку: семейство падений ПРЕДСУЩЕСТВУЮЩЕЕ - тот же модуль
test_mca09_intents_block_e_round1040 падает и на базе, без нового кода; файлы этого модуля кандидат не
менял. Это загрязнение процесс-глобального состояния между файлами, не регрессия P9 (1/5 против 1/8).

Мутации (правка исходника + прогон файла + восстановление из git; рабочее дерево после - чистое, кроме
отчёта ревьюера):

| Мутация | Упавшие тесты |
|---|---|
| M1 initiative_on = None (гейт чата не спрашивается) | test_chat_toggle_off_is_reported_as_initiative_disabled |
| M2 ветка publication.degraded отключена | test_missing_claim_table_is_reported_as_schema_absent |
| M3 ready = bool(доступность) без учёта skip | test_missing_claim_table_is_reported_as_schema_absent + test_cooldown_state_never_claims_ready_and_skip_together |
| M4 сверка базиса времени отключена | test_next_check_is_never_before_last_check |

**5. Ранее доказанное - без регрессий (перепроверено своими прогонами)**

Два независимых блока с полными наборами полей и разными mechanism/output_kind; "нет данных" не равно
нулю (никогда не проверялся: last_check_ts=null при законном remaining=0); конфликт только из
publication (записанный в payload publication_conflict даёт skip_recorded, но не conflict); probability_one -
draw не выполнялся и значения нет; кулдаун свой (scope=mechanism_own, 3600 != TTL брони 90); коды причин
только из реестров (obs.REASON_LABELS для текста, meme.SKIP_REASONS для мема); утечек текстов, промптов и
секретов нет; только аддитивность (в добавленных строках нет записи в БД и событий).

**6. Гейт и связывание строк (PM)**

requirements_gate.py check --stage review --slice MEME-INIT-DIAG --candidate 53daa257 в рабочем дереве
кандидата: 5 ошибок - candidate mismatch (в карте всё ещё f9d1cda9) и четыре mandatory not VERIFIED
(PENDING). Это учётная часть: поведение доказано, строки ещё не связаны.

PM МОЖЕТ связывать MEME-IIC-DIAG-TIMES / -RANDOM / -COOLDOWN-CONFLICT / -NO-MIX на кандидате 53daa257:
добавить пин слайса, обновить candidate_commit на 53daa257 и указать artifact-ссылки на этот отчёт (разделы
2-5) и w-p9-diag-fix.md. Повторного цикла реализации не нужно.

**7. Неблокирующие наблюдения (в бэклог слайса, объём P9 не расширять)**

- O2b (уточнение O2). Если собственный precheck диагностики бросил исключение, fallback
  {"ok": true, "coordination": "degraded"} теперь даёт не только degraded, но и skip.code=schema_absent
  с подписью "таблица квоты мемов ещё не применена". Наблюдено на своей пробе: ready=false,
  skip=schema_absent, degraded_reason=claim_table_absent, conflict=null - при том что реальная причина
  другая (сбой чтения). До правки это влияло только на объект publication; теперь это причина, которую
  увидит владелец. Требования F1 не нарушает (готовность не выдаётся, деградация видна), но в следующем
  слайсе стоит различить "таблицы нет" и "прочитать не удалось".
- O7. При open_store(...) is None (БД :memory: или без пути) боевой гейт мема таблицу брони не требует,
  а блок отдаст skip=schema_absent. В продакшене БД файловая, состояние недостижимо; для тестовых
  стендов стоит знать.
- O8. Если наблюдатель сам давно не работает (и оценка, и решение в прошлом), честная дата "следующей
  проверки" тоже в прошлом (next > last, но < now). Инвариант F2 это не нарушает: поле буквально
  означает "уже должно было произойти".

