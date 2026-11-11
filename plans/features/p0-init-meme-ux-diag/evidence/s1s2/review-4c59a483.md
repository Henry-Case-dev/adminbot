# S1-AXES / S2-ID — привязка принятого кандидата `4c59a483` (PM-запись)

Запись создана PM для привязки строк карты к уже принятому кандидату. Она не заменяет
отчёт Reviewer: все «факты Reviewer» ниже приведены как полученный вердикт, а не как
пересказ PM. Тесты указаны по путям внутри кандидата.

- Кандидат: `4c59a48338b92251b03c00e80e75d7f285ebf96b` (`fix(init-meme): three edge blockers — delivery scan, attempt mode, spool drain`)
- Ветка: `init/meme-axes`, база `c087253dd7afdbcfa0c5ee96927324dc349627b2` (`release/2.58.188`, версия 2.58.188)
- Срезы: `S1-AXES` (оси read-model, backend), `S2-ID` (сквозная идентичность попытки)
- Состояние: слайсы приняты Reviewer (третий проход); кандидат **не задеплоен**
- Изменённые файлы (8, ни одного нового): `services/initiative_diagnostics.py`,
  `services/meme_initiative.py`, `services/initiative_observer.py`,
  `services/publication_coordination.py`, `web/api/initiative_publications.py`,
  три файла тестов. DDL/новых таблиц/новых модулей в диффе нет.

## Дословные факты вердикта Reviewer

1. Delivery: доставка разрешается по последней строке, у которой есть `tg_message_id`.
   Независимый кейс `777` + 21 строка без id + `888` + 9 строк без id дал
   `confirmed / message_id=888 / run_id=run-888`; пустой журнал → `never`; строки без
   любого id → `unknown`; сбой чтения → `unknown`; сужение запроса до самой новой строки
   ломает их тест.
2. Список публикаций: опубликованный РУЧНОЙ мем, у которого этап «прикол» записал
   `mode=auto`, показывается как `manual`; фильтр `manual` его находит, `auto` — нет;
   ось диагностики согласуется; соседняя попытка остаётся `auto`.
3. Spool: 501 строка переживает мёртвый журнал и все 501 доезжают до таблицы; граница
   батча 200 не обрезает; прерванный `os.replace` сохраняет исходные байты, а повтор даёт
   205 строк без дублей; старое поведение «прочитать 500 и удалить» теряет хвост, и их
   тест на нём падает.
4. Остаточное окно, названное честно: если падает И запись в журнал, И запись в spool,
   строка не попадает ни в таблицу, ни в файл; прогон подтвердил table=0, файла spool
   нет, в логе строка `attempt LOST`. Это больше не молчаливо.
5. Серии: initiative/meme 287 passed / 4 failed — те же четыре заранее существующих
   падения `test_initiative_coordination.py`, которые падают и на `c087253d`;
   запускавшиеся web/API файлы — 197 passed / 0 failed.
6. Поведение, которое продолжает держаться: `enabled=false` только из явного OFF;
   cooldown/quota/quiet/not-enough-messages остаются `waiting`; истёкший маркер не
   блокирует; источник/scope различаются по чату; идентичность текста mint до первого
   гейта; исключение precheck → `unknown`; 422 без заголовка, 403 для не-админа.

## Привязка строк

### S1-AXES

| req_id | Итог | На чём держится |
| --- | --- | --- |
| `P0IM-AX-CONFIG` | VERIFIED | ф.6: `enabled=false` только из явного OFF, источник/scope различаются по чату, 422/403; `test_axis_configuration_false_only_from_explicit_setting`, `test_axis_configuration_is_null_when_gate_is_unreadable`, `test_configuration_names_chat_layer_instead_of_global`, `test_configuration_chat_override_is_named_as_chat` |
| `P0IM-AX-HEALTH` | VERIFIED | дословной фразы об этой оси в вердикте нет; проверено на approved-кандидате: `test_axis_health_degraded_coordination_is_not_ok` (нет таблицы брони → `degraded`, источник `meme_initiative.image_dependency`) и `test_axis_health_error_when_attempt_journal_is_absent` (нет журнала → `error`, readiness `blocked/schema`) |
| `P0IM-AX-READY` | VERIFIED | ф.6 (четыре класса `waiting`, истёкший маркер не блокирует, precheck-исключение → `unknown`); `test_axis_readiness_busy_on_live_claim_and_not_busy_when_expired` (живая бронь `busy`, просроченная — нет), `test_axis_readiness_has_no_invented_eta_after_lottery_miss` |
| `P0IM-AX-ATTEMPT` | VERIFIED | ф.2 (ось диагностики согласуется со списком по той же попытке), ф.1 (`run_id=run-888` в доставке); `test_axis_last_attempt_is_one_attempt_with_mode_and_stage` — набор полей `at/mode/run_id/outcome/stop_stage/incomplete_historical`, ранний отказ по квоте = одна попытка со своим `run_id` |
| `P0IM-AX-DELIVERY` | VERIFIED | ф.1 полностью (четыре ветки: подтверждено с `message_id`, `never`, `unknown`, сбой чтения) |
| `P0IM-AX-REUSE` | VERIFIED | инспекция диффа кандидата: только существующие модули, аддитивные поля, DDL и новых файлов нет |
| `P0IM-AX-SERVER` | PENDING | пять осей в одном ответе подтверждены (`test_mechanism_diagnostics_carries_all_five_axes`, ф.2 «ось диагностики согласуется»), но вторая половина acceptance — «клиент не собирает ВКЛ/ВЫКЛ из разных флагов и не выводит статус из отсутствия полей» — на этом кандидате не выполнена: `web/app.js` в диффе отсутствует и по-прежнему рисует `ready=false` как «выключено». Закроет `S3-OV` (`P0IM-OV-FALSEOFF`, `P0IM-OV-L1`) |
| `P0IM-BAN-ENABLED` | PENDING | backend-половина доказана (ф.6), но acceptance прямо требует «ни в backend, ни в UI»; UI-половина — `S3-OV` |
| `P0IM-BAN-CONFLATE` | PENDING | половина «отложенная/id-less отправка не считается доставленной» доказана ф.1 (`unknown`, а не `delivered`); разделение «considered ≠ публикация» показывает `S4-TRACE` (`P0IM-PB-VOCAB`, `P0IM-PB-COUNT`), доказательств по нему пока нет |
| `P0IM-BAN-NOETA` | PENDING | в acceptance назван конкретный путь `availability().next_check_ts` («подставляет now при отсутствии кулдауна»); `web/api/initiative_vitality.py` и `web/app.js` этим кандидатом не тронуты, поэтому требование не закрыто, несмотря на `next_basis` в оси |

### S2-ID

| req_id | Итог | На чём держится |
| --- | --- | --- |
| `P0IM-ID-MODE` | VERIFIED | ф.2 дословно: `mode=manual` из терминальной строки (detail JSON), фильтры честные, соседняя попытка `auto`; `test_manual_published_meme_is_manual_even_if_joke_stage_says_auto`, `test_joke_cap_rows_do_not_leak_into_other_attempts`, `test_terminal_journal_row_records_attempt_mode`, `test_manual_early_refusal_is_manual_in_the_publications_list` |
| `P0IM-ID-RUN` | VERIFIED | ф.6 (текст: идентичность mint до первого гейта) + `test_early_refusal_has_its_own_run_id`, `test_cooldown_quota_quiet_refusals_carry_run_id`, `test_text_early_refusal_has_per_chat_run_id` (ранний отказ несёт родителя чата и это не цикловой `job_id`) |
| `P0IM-ID-CHILD` | VERIFIED | `correlation_id=f"{jid}#meme_summary"` / `#meme_joke`, `holder_ref=jid`, `record_delivered_output` с тем же родителем (инспекция кода кандидата); `test_child_llm_calls_are_namespaced_under_the_parent_run`, `test_text_child_llm_calls_are_namespaced`; ф.1 — строка доставки несёт `run_id` |
| `P0IM-ID-FIELDS` | VERIFIED | мем: терминальная строка и события несут `chat_id`, `run_id`, `mode`, `request_ref`, `stage`, метки времени, вердикт и признак доставки; текст: каждое чатовое событие получает `trace_id = run_id` (`test_text_events_carry_per_chat_run_id`), `mode=auto` в read-model (`test_text_early_refusal_has_per_chat_run_id`); `manual/request_ref` для текста не имеют смысла и не выдумываются |
| `P0IM-ID-NOTEXT` | VERIFIED | `test_legacy_rows_without_job_id_are_marked_historical` (две старые строки без id остаются двумя, не склеиваются), `test_regular_attempts_are_not_marked_historical`, `test_joke_cap_rows_do_not_leak_into_other_attempts` (соседняя попытка не заражается чужой строкой) |
| `P0IM-ID-HIST` | VERIFIED | ф.1 (`rows without any id → unknown`), `test_legacy_rows_without_job_id_are_marked_historical` (`incomplete_historical`, `job_id=""`, detail по своему `attempt_id`), `test_regular_attempts_are_not_marked_historical` |
| `P0IM-ID-FINISH` | **PENDING** | одно-попыточность, устойчивый родитель и отсутствие протечки режима доказаны (ф.2, `test_manual_early_refusal_is_manual_in_the_publications_list`), НО durable-часть acceptance («без потери этапов», дефект D4 журнала) не выполнена в остаточном окне `RW-D4-BOTH-WRITE-FAIL`: при одновременном отказе журнала и spool строка теряется (см. раздел «Остаточное окно») |
| `P0IM-ID-CONC` | PENDING | в вердикте нет наблюдения о параллельных запусках в двух чатах, и в approved-серии нет проверки на конкурентную группировку/дедупликацию; закрывается `S7-ACCEPT` (`P0IM-AC-MATRIX-FAIL`, конкурирующие чаты/холдеры) или отдельным targeted probe |

Итог: привязано 12 уникальных `req_id` (20 строк инвентаря), оставлено PENDING 6 уникальных
`req_id` (15 строк инвентаря). Ни одна строка не повышена статусом «за серию зелёных
тестов в целом»: у каждого PENDING назван конкретный невыполненный пункт acceptance.

## Остаточное окно (открытый пункт, не задача владельцу)

`RW-D4-BOTH-WRITE-FAIL`
- Дефект-источник: D4 «`record_attempt` теряет строки при sqlite lock (77/24 ч, 228/7 дней)»,
  строка карты `P0IM-ID-FINISH`.
- Условие: запись строки в журнал попыток (sqlite) не удалась **и** запись в файловый
  spool тоже не удалась (диск/права/ошибка `os.replace`).
- Наблюдаемое: строка не попадает ни в `meme_initiative_attempt`, ни в spool-файл;
  пишется `WARNING [meme] attempt LOST (journal and spool unavailable) | attempt=<jid>`.
  Независимый прогон Reviewer: table=0, файла spool нет, лог `attempt LOST`.
- Что закрыто этим кандидатом: обычный отказ журнала (501 строка доезжает, батч 200 не
  обрезает, прерванный `os.replace` сохраняет байты, повтор без дублей).
- Что НЕ закрыто: требование «без потери этапов» в окне двойного отказа.
- Проверяет агент, не владелец. Триггер перепроверки: следующий кандидат этого эпика и
  `S7-ACCEPT` (обрыв после LLM/Image, старые неполные записи), где остаточное окно должно
  быть либо закрыто durable-путём, либо зафиксировано как принятый риск с явной записью.

## Учёт S3-OV (чтобы не столкнуться)

`S3-OV` (обзор UI) начат отдельной полосой Builder на той же ветке `init/meme-axes`
от `4c59a483`; на момент записи коммитов S3 в ветке нет, правки ожидаются в
`web/app.js`, `web/index.html`, `web/static/app.css`, `tests/js/initiative_ui_rework_test.js`.

Строки, которыми владеет S3-OV (14 уникальных id, 21 строка инвентаря):
`P0IM-OV-CARDS`, `P0IM-OV-FALSEOFF`, `P0IM-OV-PERCHAT-CAUSE`, `P0IM-OV-FRESH`,
`P0IM-OV-HEADER`, `P0IM-OV-L1`, `P0IM-OV-L2`, `P0IM-OV-L3`, `P0IM-OV-ACT`,
`P0IM-OV-COORD`, `P0IM-OV-LIST`, `P0IM-OV-NODUMP`, `P0IM-OV-SAMPLE`, `P0IM-OV-SILENT`.

Не пересекаются: `P0IM-BAN-ENABLED`, `P0IM-AX-SERVER` и `P0IM-BAN-NOETA` остаются
строками `S1-AXES`, хотя их UI-половину физически закроет работа S3. S3 не должен
помечать их VERIFIED в своих отчётах, а S1-срез не может считаться закрытым по gate,
пока эти строки не доказаны: это одна и та же работа, учтённая один раз.
`P0IM-S6-*` (свежесть, TZ, scope) остаются за `S6-FRESH` и не переходят в S3.

## Оговорки

- Кандидат не задеплоен; строки с `live_required: true` в этих срезах остаются PENDING,
  пока нет реального UI/live-доказательства.
- Четыре падения `test_initiative_coordination.py` заранее существуют и падают также на
  базе `c087253d`; они не относятся к этим срезам, но остаются видимыми в серии.
