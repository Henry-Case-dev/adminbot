# Привязка доказательств к выложенной 2.58.197 (итоговая сверка карты)

Эпик `p0-init-meme-ux-diag`. Документ — **индекс доказательств**: для каждой обязательной строки
карты названо, чем именно подтверждён её пункт приёмки на выложенной сборке. Новых требований,
кода, релиза и задач здесь нет. Статусы строк правит PM в `requirements-map.json` по этому индексу.

Правило закрытия, применённое ниже: строка считается `VERIFIED`, если её пункт приёмки **исполнен**
независимо (Reviewer, тест, e2e, живое чтение) на коде, **побайтово совпадающем** с выложенным
(§2), и для `live_required` есть производственное наблюдение выложенной сборки хотя бы для
наблюдаемой части пункта; ненаблюдаемая часть названа в наблюдении. Строки, где живая часть —
единственный носитель смысла и не наблюдалась, остаются открытыми (§5).

## 1. Факты выкладки

| Поле | Значение |
|---|---|
| Версия / ветка | **2.58.197**, `release/2.58.197` |
| Код (deployed SHA) | `2587616759de31283585ffc105c91e7193c2e89e` |
| Код (Reviewer Approved) | `895764e27f6597421ac4f496853474392c95b48a` (docs `b5841bac`) |
| Рестарт | `2026-11-12T09:41:37Z`, unit active, `NRestarts=0`, `/healthz` 2.58.197 с первой попытки |
| Схема / DDL | 47 / 0; новых флагов, настроек, промптов, моделей, маршрутов, планировщиков — 0 |
| Преддеплойный снапшот | `backups/predeploy-258197-20261112T094016Z.db`, 2 557 874 176 б, `integrity=ok`, `user_version=47` |
| Откат | `c134f93d` (2.58.195), `release/2.58.195`; данные не откатываются (DDL=0) |
| Предыдущий прод | 2.58.195 `c134f93d` (2026-11-12T05:24:29Z) |
| Неудачный промежуточный | 2.58.196 `e8e2619b` (2026-11-12T08:55:40Z) → откат 09:08:28Z из-за живого дефекта OV-LIST; 2.58.197 его исправил |
| Артефакты выкладки | `release-258197/deploy.md`, `deploy-run.log`, `postdeploy-read.txt`, `artifact-hashes.txt`, `recon-258197.txt`, `live-checks-2.58.197.json`, `live-extra-2.58.197.json`, `live-ov-list-2.58.197.json`, `live-overview-2.58.197.json`, `live-ui-2.58.197.json`, `settings-parity-2.58.197.json`, `chat-config-stability-2.58.197.json`, `live-overview-chatA/chatB-2.58.197.png`, `live-memes-chatA/chatB-2.58.197.png` |

## 2. Тождество выложенного кода одобренному кандидату (проверено при этой сверке)

| Проверка | Результат |
|---|---|
| `git diff 895764e2..25876167 -- services handlers web` | **пусто** (0 строк): весь продуктовый код 2.58.197 побайтово равен одобренному `895764e2` |
| Отличие `895764e2..25876167` | только `config/settings.py` (бамп версии), 30 файлов пинов и docs/tests — продуктовая логика не менялась |
| `web/app.js` в `895764e2` и в `25876167` | один и тот же blob, `sha256 0d9dcaae3e31f51e8774ad70585f08904603f5610b0cdcd44224085657eeb98c`, 2 341 029 б |
| Кумулятивно `c134f93d..25876167` | 48 файлов (45 M, 3 A, 0 D), +2788/−91: 8 кода, 8 тестов, 3 evidence, 30 пинов |
| Код доставки/учёта S5b в `c134f93d..25876167` | правок `publisher_not_bound`/`not_delivered` нет (diff `services/meme_initiative.py` содержит только `merge_terminal_facts`, `llm`/`prompt`/`image_format` факты и `_default_image`) |

Следствие: доказательства, снятые на `895764e2`/`3b1c4ba9`/`21a3aef7`, применимы к 2.58.197 без
перепрогона. Доказательства, снятые на 2.58.194–2.58.195, применимы там, где соответствующий
код-путь не менялся; это указано в каждой строке.

## 3. Использованные артефакты (роль)

- **Выкладка/состав:** `release-258197/deploy.md` §1–§3, `deploy-run.log`, `postdeploy-read.txt`, `recon-258197.txt`.
- **Живые данные (production, read-only, без сообщений в чаты):** `live-checks-2.58.197.json` (diagnostics, meme_settings, publications, фильтры, трассы, Inspector, ov_sample, secret_scan), `live-extra-2.58.197.json` (403 не-админу, image_module/провайдер/heartbeat, маркер), `live-ov-list-2.58.197.json`, `live-overview-2.58.197.json`, `live-ui-2.58.197.json`, PNG обоих чатов.
- **Effective-конфигурация:** `settings-parity-2.58.197.json`, `chat-config-stability-2.58.197.json`, `release-258197/deploy.md` §4.
- **Независимое ревью:** `evidence/closure-train/review-3b1c4ba9.md` (Approved; ledger по строкам + точечные re-review test-only fix и OV-LIST fix), `evidence/closure-train/review-931945b7.md` (Needs Fixes, закрытые блокеры), `evidence/final-train/review-5d599ca1.md`, `evidence/final-train/review-262f7f18.md`.
- **Привязки Builder/PM:** `evidence/closure-train/binding-895764e2.md`, `evidence/final-train/binding-durability-926b093a.md`, `binding-f984f06a.md`, `binding-ban-conflate-2d41f2b3.md`.
- **Ранее одобренные привязки:** `evidence/s1s2/review-4c59a483.md`, `evidence/s3ov/binding-726736ee.md`, `evidence/s3ov/binding-258191.md`, `evidence/s2id/pm-binding-16cdb3b8.md`, `evidence/s5b/binding-e92cdcd5.md`, `evidence/s6/binding-258194.md`, `evidence/s7accept/binding-992f45ab.md` + `matrix-prod.json`, `evidence/r0/diagnosis-2.58.188.md`.
- **Предыдущие живые прогоны:** `release-258194/live-overview-2.58.194.json`, `release-258194/live-modes-2.58.194.json`, `release-258194/live-peek-2.58.194.json`, `release-258195/live-ov-sample-2.58.195.json`, `release-258195/live-detail-2.58.195.json`.

## 4. Построчная привязка (77 уникальных требований / 114 строк)

Формат: `req_id` — статус на 2.58.197 — на чём держится.

### 4.1 A0-ARCH

| req_id | Итог | Основание |
|---|---|---|
| `P0IM-A0-CONTRACT` | VERIFIED | `architecture.md` (DESIGN READY): родитель — существующие `job_id` журнала мема и `trace_id` mca_events, новые колонки/таблицы не нужны; child-ID `{jid}#meme_summary/#meme_joke`; с документом сверены зависимые срезы (`slice-graph.json → design_ref`, `ID-CHILD`/`ID-FIELDS`/`ID-MODE`). Артефакт: `plans/features/p0-init-meme-ux-diag/architecture.md` |

### 4.2 R0-INV (read-only расследование `c087253d`)

| req_id | Итог | Основание |
|---|---|---|
| `P0IM-R0-PERCHAT` | VERIFIED | `diagnosis-2.58.188.md` §5: таблица по каждому чату и механизму с раздельными полями; на 2.58.197 та же раздельность перечитана в `live-checks-2.58.197.json` (на чат: `configuration`, `readiness`, `last_attempt`, `last_delivery` с `message_id`) |
| `P0IM-R0-COMPARE` | VERIFIED | §5: оба чата в одном окне по конфигурации, last_attempt, last_sent, message_id, квоте, кулдауну, провайдеру и броням; пять различий квалифицированы как обычные, не дефект. На 2.58.197 различия (кулдаун A 3 ч 01 мин против B 5 ч 07 мин; у текста A «мало сообщений», B «может сработать сейчас») объяснены состояниями, а не дефектом |
| `P0IM-R0-SOURCES` | VERIFIED | §2–8: каждый вывод привязан к источнику (mca_events, проекция речи, журнал этапов, publication_claims, ledger outputs, journald, БД аналитики, код `c087253d`); неполученные источники — §9 |
| `P0IM-R0-SEPARATE` | VERIFIED | §4–5: конфигурация (значение + источник override) отделена от состояния последнего события; кулдаун/квота/тихие часы/нехватка сообщений описаны как пропуски, не сбой |
| `P0IM-R0-MEMECHAIN` | VERIFIED | §2–7: по неудачным `/meme` участки (апдейт, права, удаление, маркер, гейты, чтение, LLM A/B, image API, бронь, отправка) подтверждены или честно помечены неизвестными |
| `P0IM-R0-GAP` | VERIFIED | §9: отсутствующая трасса названа точным отсутствующим участком; гипотезы вынесены отдельно |
| `P0IM-R0-CODE-DEFECTS` | VERIFIED | §3/§10: перечень подтверждённых кодом проблем с файлом и строкой, места правок и очередь; неподтверждённое вынесено отдельно |

### 4.3 S1-AXES

| req_id | Итог | Основание |
|---|---|---|
| `P0IM-AX-CONFIG` | VERIFIED | живой payload обоих чатов: `configuration {enabled:true, source:"meme_settings", scope:"mixed", layers:[module_gate/observer/chat_toggle/meme_settings/image_module]}`; ветки OFF/null и слой чата — `test_p0im_s6_fresh.py` (12 passed на выложенном дереве) и `review-4c59a483` |
| `P0IM-AX-READY` | VERIFIED | живой `readiness {state:"waiting", reason:"cooldown_active", reason_class:"cooldown", next_eligible_at, next_basis:"cooldown"}` у мемов; у текста — своя причина (`not_enough_messages`); состояния busy/blocked/unknown — тесты `test_meme_init_diagnostics.py`/`test_p0im_s6_fresh.py` |
| `P0IM-AX-ATTEMPT` | VERIFIED | живой `last_attempt {at, mode:"auto", run_id:"meme:-1004482340693:2026-11-12:e526b274a77d", outcome:"skipped", stop_stage:"skipped", incomplete_historical:false}` — тот же `run_id`, что в списке попыток |
| `P0IM-AX-DELIVERY` | VERIFIED | живой `last_delivery {status:"confirmed", at, destination, message_id:11112, run_id}`; «никогда не было»/`unknown` — тесты; отложенная отправка не выдаётся за доставку (`deferred 5` при `delivered 13`) |
| `P0IM-AX-HEALTH` | VERIFIED | живой `health {state:"ok", dependencies:[attempt_journal ok, publication_precheck ok, image ok]}`; «нет данных» и ошибка чтения не превращаются в ошибку механизма — `test_axis_health_*`, `test_unreadable_config_is_unknown_not_a_default` |
| `P0IM-AX-SERVER` | VERIFIED | все пять осей в одном ответе на чат; клиент не собирает «включено» из разных флагов — `web/app.js` читает `configuration.enabled`/`readiness`/`last_*`, это проверено Reviewer при ревью closures и подтверждено живым payload (карточка «неизвестна (квота не прочитана)» вместо вывода из отсутствия поля) |
| `P0IM-AX-REUSE` | VERIFIED | дельта 2.58.195→2.58.197 — 8 продуктовых файлов, новых таблиц/сервиса/state machine/цикла нет (аудит `review-3b1c4ba9`); живые оси приходят существующими `initiative_diagnostics`/`initiative_publications` |
| `P0IM-BAN-ENABLED` | VERIFIED | живой прод обоих чатов: `configuration.enabled=true` одновременно с `readiness.state="waiting"` (кулдаун/нехватка сообщений); карточка «Мемы ВКЛ … Сейчас: ждёт: кулдаун…»; `enabled=false` встретилось только от явной настройки (`disabled_by_setting`, исторический чат) |
| `P0IM-BAN-NOETA` | VERIFIED | живой `next_eligible_at` только с названным базисом (`next_basis:"cooldown"`); карточка «не раньше 12.11 14:53 (по собственному кулдауну)»; текст — «точное время не назначено — рассматривается на ближайшем проходе»; «сейчас» не подставляется |
| `P0IM-BAN-CONFLATE` | VERIFIED | живые счётчики одного окна (A): `checked 323 / decided 323 / generated 1 / published 12 / delivered 13 / pending 5 / deferred 5`, B: `354/354/1/25/26/13/13`; `considered` не считается публикацией, `deferred` не считается доставленным; правило `generated` — по доказанной картинке, не по этапу `publish` (`test_generated_is_not_considered_and_not_published`, `review-5d599ca1`) |

### 4.4 S2-ID

| req_id | Итог | Основание |
|---|---|---|
| `P0IM-ID-RUN` | VERIFIED | живой ранний отказ уже несёт `run_id` (`…:e526b274a77d`, `stop_stage:"skipped"`); mint до первого гейта — `test_early_refusal_has_its_own_run_id`, `test_cooldown_quota_quiet_refusals_carry_run_id`, текст `test_text_early_refusal_has_per_chat_run_id` (`review-4c59a483`) |
| `P0IM-ID-MODE` | VERIFIED | живой `mode:"auto"` отдельным полем + `facts.attempt_mode:"automatic"` в терминальной строке; `manual` из терминальной строки — `test_manual_published_meme_is_manual_even_if_joke_stage_says_auto`, `test_terminal_journal_row_records_attempt_mode` |
| `P0IM-ID-CHILD` | VERIFIED | живой detail: `full_text.steps[].correlation_id = "meme:-1002661910336:2026-11-12:16804c348dd7#meme_summary"` и `#meme_joke` под тем же `job_id`; `holder_ref`/`record_delivered_output` с тем же родителем — инспекция кода + `test_child_llm_calls_are_namespaced_under_the_parent_run` |
| `P0IM-ID-FIELDS` | VERIFIED | живая терминальная строка несёт `job_id`, `mode`, `ts`, `stage`, `outcome`, `reason_code`, `delivered`, `chain_len`; события — `trace_id=run_id` (`test_text_events_carry_per_chat_run_id`); `chat_id` — в payload и идентификаторах попытки; `review-4c59a483` |
| `P0IM-ID-NOTEXT` | VERIFIED | `test_legacy_rows_without_job_id_are_marked_historical` (две строки без id остаются двумя), `test_joke_cap_rows_do_not_leak_into_other_attempts`; живой `incomplete_historical:false` у новых строк |
| `P0IM-ID-HIST` | VERIFIED | `incomplete_historical` в живом payload; `test_legacy_rows_without_job_id_are_marked_historical` (`job_id=""`, detail по своему `attempt_id`), `test_regular_attempts_are_not_marked_historical` |
| `P0IM-ID-FINISH` | VERIFIED | удержание строки и перенос ровно один раз, полный JSON без усечения, потолок 200 — `binding-durability-926b093a` §4–§6 (реальная SQLite, подмена обоих носителей, мутации D0–D3); Reviewer `review-3b1c4ba9` подтвердил неизменность пути (61/40/44 passed); живая попытка — одна связная строка с 2 этапами |
| `P0IM-ID-CONC` | VERIFIED | `test_two_ledgers_in_two_threads_hold_and_flush_without_loss` (10 удержаний → 10 строк, без потерь и дублей; 5 прогонов, флака нет); Reviewer `review-5d599ca1`/`review-3b1c4ba9` — строки продолжают действовать, файл `test_evol014` зелёный (61 passed) |

### 4.5 S3-OV

| req_id | Итог | Основание |
|---|---|---|
| `P0IM-OV-CARDS` | VERIFIED | кадр прода 1280×950 (`live-overview-chatB-2.58.197.png`): две равнозначные карточки, в каждой все оси (Разрешено / Слои решения / Сейчас / Дальше / Последняя проверка / Последняя попытка / Последняя отправка / Дневная квота / Кто может изменить); технический код только в скобках при человеческой формулировке |
| `P0IM-OV-FALSEOFF` | VERIFIED | живой кадр: «Мемы **ВКЛ** … Сейчас: ждёт: кулдаун, осталось 5 ч 7 мин (код: cooldown_active)» — `ready=false` не рисуется «выключено»; причины `not_enough_messages`/квота/тихие часы/недоступность картинок — JS-набор `initiative_ui_rework` (O1/O2) |
| `P0IM-OV-PERCHAT-CAUSE` | VERIFIED | живой кадр: у текста A «мало сообщений в окне (код: not_enough_messages)», у текста B «может сработать сейчас — ничего не мешает»; у мемов — свой кулдаун в каждом чате; режим «Другой чат» снимался на 2.58.194 (`live-modes-2.58.194.json`), разница подана как разные состояния |
| `P0IM-OV-FRESH` | VERIFIED | живой кадр: «снимок: 12.11 09:46 (сервер)» + кнопка «Обновить»; «нет данных»/ошибка не окрашиваются как OFF (карточка «неизвестно — настройку не удалось прочитать» без метки «выключено») |
| `P0IM-OV-HEADER` | VERIFIED | живой кадр: имя чата, строка «пояс чата не задан — UTC (заводское значение, не часы сервера)», серверный штамп, переключатель «Этот чат / Другой чат / Сравнить чаты», «Обновить»; агрегаты всех чатов не подмешиваются |
| `P0IM-OV-L1` | VERIFIED | живой кадр: «Текстовая инициатива **ВКЛ**», «Разрешено: включено — глобальный выключатель», «Сейчас: ждёт…»; признак ошибки отсутствует при отсутствии неисправности |
| `P0IM-OV-L2` | VERIFIED | живой кадр: одна главная причина («ждёт: кулдаун, осталось…», «мало сообщений в окне»), остальное раскрывается; время — на серверном основании («не раньше … (по собственному кулдауну)»), без обратного отсчёта как расписания |
| `P0IM-OV-L3` | VERIFIED | живой кадр: последняя проверка (09:43/09:46), последняя попытка с исходом, последняя подтверждённая отправка (сообщение 11112 / 1211393), дневная квота (2/3); у текста — «неизвестна (квота не прочитана)», т.е. 0 и «неизвестно» различаются; предел мемов подписан |
| `P0IM-OV-ACT` | VERIFIED | кнопки «Открыть настройки …» и «Показать попытку →» присутствуют на обеих карточках в живом кадре; переход в существующие «Публикации»/«Диагностику» с тем же `run_id` — `tests/ui_initiative_rework_e2e.py` и JS-набор на выложенном дереве. Живой клик не прокликивался (см. §6) |
| `P0IM-OV-COORD` | VERIFIED | живой payload: `publication.state="released"`, `conflict=false`, `coordination="ok"`, `manual_priority_expired=true` → полосы координации нет; полоса при живом держателе — `release-258194/deploy.md` §6(в) и JS `closureTrainSuite` |
| `P0IM-OV-LIST` | VERIFIED | живой кадр и `live-ov-list-2.58.197.json`: 5 строк на чат, метка «автоматически» у всех, тип «Мемы», время, итог «Пропуск · пропущено · кулдаун», ссылка «Все публикации →»; «способ не записан» — 0 из 5; ручных попыток в окне 0 (метка «вручную (/meme)» покрыта JS-тестом живой формы) |
| `P0IM-OV-NODUMP` | VERIFIED | живой кадр 1280×950: карточки/строки, без JSON-дампа и многоколоночной таблицы; мобильная ширина 390×844 — замеры `evidence/s7accept/matrix-prod.json` (визуальные проверки, `scrollWidth==clientWidth`), код вёрстки не менялся после `895764e2` |
| `P0IM-OV-SAMPLE` | VERIFIED | живой кадр 2.58.197: п.1 «Разрешено: ВКЛ | Сейчас: ждёт: кулдаун, осталось 5 ч 7 мин»; п.3 «Последняя отправка: подтверждено · 12.11 09:01 · чат · сообщение 1211393»; п.4 действие «Показать попытку →»; п.2 (изображение создано, отправка отложена) — живого кадра в окне нет: данные есть (`deferred 5`, B 08:53:39 `generated=true`, `publisher_not_bound`, размер 1 843 784 + sha256 в `release-258197/deploy.md` §5), отрисовка ветки — JS/e2e. Формулировки отличаются от образца, семантика совпадает |
| `P0IM-OV-SILENT` | VERIFIED | ветка «бот решил промолчать» — `initiative_ui_rework_test.js` (не OFF, не сбой) и `ui_initiative_rework_e2e.py`; в текущем живом окне молчания нет (текст A ждёт сообщений, B «может сработать сейчас»), и ни в одном состоянии карточка не показывает «выключено» — это наблюдаемо живьём |

### 4.6 S4-TRACE

| req_id | Итог | Основание |
|---|---|---|
| `P0IM-PB-TRACE` | VERIFIED | живой `GET …/publications/{id}` обоих чатов: связная цепочка `considered → skipped` с `reason_code`/`reason_label`, блок `full_text` (Inspector + политика хранения), `delivery {delivered:false,message_id:null}`; у текста — только его этапы, без выдуманных «Прикол»/Image API (тест + JS) |
| `P0IM-PB-ROW` | VERIFIED | живой список: одна строка = одна попытка (время, механизм, режим, итог, причина) + detail по `attempt_id`; живой detail: `stages`, `outcome`, `delivered`, `reason_code` |
| `P0IM-PB-NOTRUN` | VERIFIED | живая цепочка содержит только реально пройденные этапы (2 из 12) — незапускавшиеся не выдаются за `skipped`; подпись «не выполнялся» — JS/`ui_initiative_rework_e2e` |
| `P0IM-PB-CODES` | VERIFIED | живой кадр: «(код: cooldown_active)» только рядом с русским объяснением, в главном слое кодов нет; API отдаёт `reason_code` + `reason_label` |
| `P0IM-PB-STEP` | VERIFIED | живой шаг: `duration_ms=null` + `duration_reason="step_timing_not_recorded"` (не 0), `request_id` из записи + `request_id_source="journal_job_id"`, `llm {provider:null,…,reason:"not_recorded_in_stage_record"}`, `reason_label` |
| `P0IM-PB-VOCAB` | VERIFIED | живой payload: `data_state="ok"`, `stale=false`, поля `stale_reason/stale_age_seconds/stale_window_seconds/stale_window_basis`, `no_data_reasons`; счётчики `deferred 5 / unknown 0 / not_delivered 305 / delivered 13` раздельны; `stale≠no_data` — `test_stale_snapshot_is_not_no_data_and_needs_a_recorded_window` |
| `P0IM-PB-COUNT` | VERIFIED | живые счётчики одного окна: `total/checked/decided/generated/published/delivered/pending/llm_calls 2/images 1/text 26/meme 297`; `considered` не учтён публикацией; раздельные счётчики — `test_counts_carry_llm_calls_and_images_separately` |
| `P0IM-PB-FILTERS` | VERIFIED | живой проход: `kind` (meme 297 / text 26), `mode` (auto 323 / manual 0), `outcome` (published 12 / deferred 5 / failed 0), `reason` (cooldown 277), `days` 7/0/90, пагинация `limit/offset` (0/1/5, `next_offset`), ретенция ≤90 (`days=91` → 422), границы `limit 0/500`, `offset −1` → 422. «Поиск» реализован серверными фильтрами `reason`/`attempt_id` (свободного текстового поиска в API нет — см. §7) |
| `P0IM-PB-ACCESS` | VERIFIED | живой прод: обычный Inspector 200 с `preview`/`hierarchy`; запрос с `correlation_id` → `not_recorded`, `messages=[]`, `system=""`, без `preview`/`hierarchy`, `masked=true`, `retention` «24 записи процесса»; не-админ → **403** на обоих чатах; политика «полный текст исторически не сохранялся» — в `full_text.storage`. Положительный случай своей записи кольца (маскировка секрета, чужой чат без текста, вытеснение 25-м вызовом) — независимая проба Reviewer на `3b1c4ba9`, код побайтово тот же |
| `P0IM-PB-LLM` | **PENDING** | см. §5.1: живого носителя нет — 3 (A) и 4 (B) попытки после рестарта остановились до LLM; живьём наблюдён только честный `null` с причиной |
| `P0IM-PB-MANUAL` | VERIFIED | живой маркер: `manual_priority_until`, `active=false`, `expired=true`, `state="released"`; слияние факта снятия в ТУ ЖЕ терминальную строку, повторное снятие = false, исторические — `release_not_recorded` (`test_release_is_appended_to_the_same_terminal_attempt`, `test_detail_terminal_row_carries_manual_priority_release`, `review-3b1c4ba9`). Живой ручной запуск запрещён владельцем (2026-11-12 §6) — `live_required` исправлен на false (§7) |

### 4.7 S5-MEME

| req_id | Итог | Основание |
|---|---|---|
| `P0IM-MM-MARKER` | VERIFIED | живой прод: `manual_priority_until` в прошлом, `manual_priority_active=false`, `manual_priority_expired=true`, `claim_expires_at=null`, полосы нет — истёкший `until` не рисуется текущим блоком; TTL 600 и снятие на успехе/отказе/исключении/отмене — `test_p0im_s5_meme_marker_interrupt.py` (16 passed на выложенном дереве) |
| `P0IM-MM-TRACE` | VERIFIED | шаги ручного запуска (получение команды, RBAC, удаление команды первым сетевым действием, запись приоритета, вход/выход этапов, одна фотография без подписи, отказ одной репликой) — `tests/test_meme_command_autodelete.py` (18 passed) + `test_p0_publication_hotfix` (45) в серии 519 passed на `25876167`; живой не-админ → 403 без текста. Живого ручного запуска нет по запрету владельца (это не недобор) |
| `P0IM-MM-PRIO` | VERIFIED | снятие на успехе/отказе/исключении/отмене, `release` не убивает второй маркер, durable-восстановление прерванной строки `test_b1_interrupted_row_is_finalised_not_resent`, `test_manual_new_messages_do_not_cancel_ready_meme`, повторное снятие — no-op; файлы зелёные на выложенном дереве (16 + 45 + 204) |
| `P0IM-MM-DEFER` | VERIFIED | `test_automatic_reports_real_conflict_before_generation`, `test_automatic_collision_after_generation_keeps_facts_and_does_not_send` (серия 519 passed); показ «ждёт» с причиной — O1/O4 JS + живой кадр (`publication.state=released`, полосы нет при отсутствии конфликта) |
| `P0IM-MM-SECRET` | VERIFIED | живой прод: не-админ 403 на обоих чатах, `secret_scan` по 68 414 символам = 0 совпадений (`authorization/api_key/password/secret/cookie/bot_token/bearer/sk_live`), чужой чат не получает ни строк, ни текста (`test_detail_does_not_mix_chats`), промпты в Telegram не публикуются (отправляется фото без подписи) |

### 4.8 S5b

| req_id | Итог | Основание |
|---|---|---|
| `P0IM-S5B-NODISCARD` | VERIFIED | независимая проверка Reviewer в изолированном worktree с фейковым отправителем (`binding-e92cdcd5` §2): строка `queued`, байты файла побайтово равны оплаченным, `sha256` payload совпал, `artifact.preserved=true`, `delivery=not_sent`, ветка `preserved=false` с причиной, восстановление после перезапуска ровно одной отправкой, истечение срока без отправок; новых очередей/планировщиков нет. Живая половина: отложенная попытка B 08:53:39 с `publisher_not_bound`, сохранёнными размером и sha256 (`release-258197/deploy.md` §5); код доставки в 2.58.197 не менялся (§2) |
| `P0IM-S5B-DELIVERY-FACT` | VERIFIED | живой read-model 2.58.197: `quota {used 2, delivered 2, not_delivered 0, not_delivered_reasons {}}` + `last_delivery {status, message_id}` — счётчики изображений/отправок раздельны; живой экран 2.58.194 (код тот же): «Генерации сегодня: 3 / 3 · израсходовано без отправки: 1 (отправитель не привязан в этом процессе)» |
| `P0IM-S5B-QUOTA` | VERIFIED | то же живое основание: раздельные `generated 1 / images 1 / delivered 2 / not_delivered 0` на 2.58.197 и живая подпись «израсходовано без отправки: 1 (…)» на 2.58.194; списание слота без доставки показывается с причиной, а не молчит |

### 4.9 S6-FRESH

| req_id | Итог | Основание |
|---|---|---|
| `P0IM-S6-EFFECTIVE` | VERIFIED | живой payload обоих чатов: `configuration.layers` содержит `{gate:"image_module", layer:"global", enabled:true, source:"image_module"}`, `meme.image_provider {available:true, configured:true, module_enabled:true, reason:"ok", model:"qwen-image-3-pro"}`, `heartbeat {ok:false, last_tick_ts:null, note:"heartbeat≠outcome…"}` — честный `null` при отсутствии тика; новых панелей нет, строки в существующей технической панели; сохранённые настройки не менялись (§4.10) |
| `P0IM-S6-SCOPE` | VERIFIED | живой payload каждого чата несёт свой `chat_id`; серверный штамп «снимок: 12.11 09:46 (сервер)»; клиентский guard `scopeEpoch` + `payload.chat_id`, один in-flight и хвост — `s6FreshSuite` в `initiative_ui_rework_test.js` (живой race не воспроизводился, см. §6) |
| `P0IM-S6-TZ` | VERIFIED | живой кадр: «пояс чата не задан — UTC (заводское значение, не часы сервера)», `tz_source=unknown` честно; положительная ветка IANA и смещение лето/зима — `test_timezone_offset_follows_the_instant`, `test_time_block_names_chat_timezone_and_its_layer`; сохранённые настройки владельца не менялись |
| `P0IM-S6-EXPIRED` | VERIFIED | живой прод: истёкший маркер и бронь не дают «занято» (`manual_priority_expired=true`, `claim_expires_at=null`), полосы координации нет |

### 4.10 S7-ACCEPT

| req_id | Итог | Основание |
|---|---|---|
| `P0IM-AC-NODUP` | VERIFIED | аудит Reviewer `review-3b1c4ba9`: 7 продуктовых файлов + тесты/evidence, нет новых таблиц/колонок/миграций, флагов/настроек/промптов/моделей/эндпоинтов, планировщика, задачи, второго пайплайна и логического хардкода; живой состав 2.58.197: DDL 0, новых флагов/настроек 0, маршрутов 0; сохранённые настройки не изменены (§4.10 AC-SETTINGS) |
| `P0IM-AC-SETTINGS` | VERIFIED | `settings-parity-2.58.197.json`: `config_global`, `overrides_map`, `prompts_catalog`, 4×`prompt_versions`, `meme_settings` обоих чатов — sha256 до = после; единственное расхождение — волатильный `modules/3/gate/observed_at` в per-chat `/api/config` (различается между любыми двумя вызовами), latest `updated_at` у всех 623 items — 2026-11-11, до релиза; `all_match=false` относится только к этому полю |
| `P0IM-AC-UI-HOME` | VERIFIED | живой кадр: модуль внутри существующего раздела «Модули», свои тёмная тема/компоненты/табы («Обзор / Текстовая инициатива / Мемы / Публикации / Диагностика»), паттерн «обзор → попытка → этапы → факты», новых страниц нет; мобильные замеры 390×844 в `matrix-prod.json` |
| `P0IM-AC-MATRIX-CONFIG` | VERIFIED | `matrix-prod.json`: 12 проверок CONFIG пройдены (factory/global/chat/OFF/unknown/кулдаун/квота/сообщения/L1) + `test_probability_one_is_reported_as_no_draw` (жребий не нужен при 100%) и честные строки «промолчал/без жребия»; `review-3b1c4ba9`: новых acceptance-флагов нет, поведение безусловное, ON и OFF `image_module` покрыты |
| `P0IM-AC-MATRIX-FAIL` | VERIFIED | два новых реальных теста на `25876167`: `test_provider_failure_after_llm_stages_is_one_failed_attempt` (обрыв после A/B → один failed, без `publish`/доставки) и `test_empty_image_content_is_an_honest_failure_not_publication` (`ok=True, content=None` → честный `empty_content`); плюс пять привязанных проверок (ранние гейты с `job_id`, конфликт отправок, старые неполные записи, `delivery_unknown`); Reviewer подтвердил утверждения тестов |
| `P0IM-AC-MATRIX-MANUAL` | VERIFIED | `test_manual_run_bypasses_quota_cooldown_and_closed_gate` (ручной при исчерпанной квоте), `test_automatic_reports_real_conflict_before_generation` (авто откладывается с причиной), живое истечение `manual_priority_until` 00:34/09:42Z (ожидание не показывается); живой ручной запуск не выполнялся по запрету владельца и не является требованием |
| `P0IM-AC-MATRIX-RBAC` | VERIFIED | матрица: 403 не-админу, 422 без чата, отсутствие смешения чатов; живой скан 68 414 символов = 0 утечек; живой 403 на Inspector обоих чатов; подтверждение реального сообщения Telegram — `last_delivery.message_id` 11112/1211393; конкурирующие держатели — `test_two_workers_in_one_chat_publish_exactly_once` |
| `P0IM-AC-MATRIX-UI` | VERIFIED | матрица: 4 проверки + 11 скриншотов (1536×960 и 390×844, гонка 2.4 с, чужой `chat_id`, истёкший маркер); независимые проверки Reviewer на кандидате: три Playwright e2e (`ui_inspector_exact` 142/0, `ui_meme_ui_fields` 0, `ui_initiative_rework` те же 2 предсуществующих) + Browser Use на реальном Chrome; живые кадры 2.58.197 обоих чатов. TMA-хост на устройстве — ограничение среды (см. §6) |
| `P0IM-AC-ORDER` | VERIFIED | порядок соблюдён: read-only фактчек `c087253d` → точечные правки data-contract/telemetry/API/frontend → независимое ревью → 2.58.191–197; посторонние улучшения в приёмку не включались (этот документ фиксирует только строки карты) |
| `P0IM-AC-POLICY` | VERIFIED | живой `configuration.enabled=true` в обоих чатах, OFF/SHADOW нет; DDL 0, новых флагов/настроек/лимитов 0 (`deploy.md` §1); функция не отключалась |
| `P0IM-AC-POSTREL` | VERIFIED | живые кадры обоих чатов (обзор + «Мемы»), артефакты реальной доставки (`last_delivery` сообщение 11112 / 1211393, `mca_bot_outputs`), независимое ревью (`review-3b1c4ba9`), статус прода (`postdeploy-read.txt`, `/healthz 2.58.197`, схема 47) |
| `P0IM-AC-DONE` | **PENDING** | свёртка: закрывается только после всех остальных строк; остаётся `P0IM-PB-LLM` (§5.1) |

### 4.11 P0IM-OV-HONEST

| req_id | Итог | Основание |
|---|---|---|
| `P0IM-OV-HONEST-LINE` | VERIFIED | живой кадр 2.58.197: «Последнее действие: 12.11 09:46 · Мемы — пропущено», т.е. реальный записанный факт; при непустом журнале ложное «нет данных» не выводится; «нет данных» остаётся для честной пустоты (`release-258194/live-overview-2.58.194.json` — «Последнее действие: нет данных» при пустом журнале текста) |
| `P0IM-OV-HONEST-UNAVAIL` | VERIFIED | живой кадр (снимок ещё не прочитан): карточка честно пишет «Разрешено неизвестно — настройку не удалось прочитать» и «нет данных», не рисуя OFF, при этом записанные попытки механизма не отменяются; штамп «снимок ещё не прочитан» отделён; DOM-три состояния + мутация C — `evidence/ov-honesty-258193.md` |

## 5. Открытые строки (не закрыты, ложный green не ставится)

### 5.1 `P0IM-PB-LLM` (строки `items[23]`, `additional_requirements[44]`)

Статус: **PENDING** (`live_required=true`, `live_when=preprod`).

Что уже есть:
- Reviewer `review-3b1c4ba9` принял реализацию и валидность тестов: `_llm_identity` (провайдер/модель,
  `slot=null` + `slot_not_used`, честная причина `custom_step_hook` для тестового шва),
  `_prompt_identity` (source/revision/sha12, без текста), `prompt_sha12` и `api.status/format/bytes`
  этапа C; `test_llm_identity_is_short_and_full_text_stays_out_of_journal`,
  `test_detail_carries_llm_identity_without_full_text`, `test_detail_full_text_is_existing_inspector_or_honest_not_recorded`;
- код побайтово равен выложенному (§2);
- живьём наблюдён **честный null**: `llm {provider:null, model:null, slot:null, recorded_keys:[],
  reason:"not_recorded_in_stage_record"}` — текущие настройки не выдаются за фактический вызов.

Чего не хватает: **живой попытки, дошедшей до LLM A/B и Image API** после рестарта. Факт:
`live-extra-2.58.197.json` — 3 попытки A и 4 попытки B, у всех `llm_stages: []`, `api_stages: []`;
`deploy.md` §7 фиксирует то же. Пункт приёмки называет **фактических** провайдера/модель и
**реально отправленные** messages — это нельзя доказать швом клиента, только живой попыткой.

Точное условие получения доказательства (агентское, без сообщений в чаты): первая естественная
автоматическая мем-попытка после окончания кулдауна (A: 3 ч 01 мин, B: 5 ч 07 мин от 09:43/09:46Z;
остаток квоты 1 в каждом чате, сброс 2026-11-13T00:00:00Z). Читать существующим
`GET /api/initiative/publications/{attempt_id}` → `chain[].facts.llm|prompt`, `api`; затем привязать
живые значения к строкам. Никаких действий владельца не требуется.

## 6. Честные границы (что НЕ заявлено)

1. **Положительный случай `PB-ACCESS`** (своя запись кольца, маскировка, чужой чат) вживую на
   2.58.197 не наблюдался: после рестарта ни одна попытка не дошла до LLM, кольцо пусто. Доказан
   независимой пробой Reviewer на побайтово том же коде.
2. **Живой ручной `/meme`** не запускался (запрет владельца 2026-11-12 §6) — ни для `PB-MANUAL`,
   ни для `MM-*`, ни для `AC-MATRIX-MANUAL`. Инженерная половина доказана изолированным вызовом
   обработчика, read-model и JS-тестами на выложенном коде.
3. **Живой deferred→delivered цикл S5b** (`WO-258194-S5B-DEFERRED`) не наблюдался — это
   добровольное пост-релизное наблюдение агентов, не acceptance-строка. Байты/причина отложенной
   попытки и счётчики «израсходовано без отправки» наблюдались.
4. **Клик «Показать попытку» в живом UI** не прокликивался; переход проверен e2e на том же коде,
   кнопка присутствует в живом кадре.
5. **Живой race смены чата** (`S6-SCOPE`) не воспроизводился: тормозить прод-запросы нельзя; guard
   проверен JS-набором.
6. **Реальный TMA-хост на устройстве** (`AC-MATRIX-UI`) не проверялся — ограничение среды, не
   acceptance-строка и не поручение владельцу.
7. **Пункт 2 образца `OV-SAMPLE`** («изображение создано, отправка отложена») живого кадра в окне
   не имеет: данные и причина есть, отрисовка ветки — JS/e2e.
8. **Retention Inspector** — 24 записи **процесса**, общие для чатов (не «на чат»); в этом круге
   живьём кольцо было пусто, политика проверена тестом вытеснения.

## 7. Толкования, зафиксированные при этой сверке

1. **`PB-FILTERS`, «поиск».** В API (`web/api/initiative_publications.py`) есть серверные фильтры
   `days/kind/mode/outcome/reason` и точный `attempt_id`; свободного текстового поиска нет.
   Приёмка «пагинация и поиск работают по серверным данным и учитывают ретенцию» закрыта этими
   фильтрами. Если владелец имел в виду свободный текстовый поиск — это отдельная новая функция,
   а не недобор этой строки.
2. **`OV-SAMPLE`, «семантика образца».** Требуется семантика, а не дословный текст: живые
   формулировки отличаются («ждёт: кулдаун, осталось 5 ч 7 мин» вместо «пауза 33 мин»), состав
   фактов тот же.
3. **`PB-MANUAL`, `live_required`.** Флаг исправлен на `false`: владелец 2026-11-12 §6 прямо
   запрещает выполнять команду от его имени и требует доказывать доступными средствами
   (изолированный вызов обработчика, read-model, тесты). Оставлять `live_required=true` значило бы
   требовать запрещённого действия. Инженерная проверка остаётся обязательной и выполнена.
4. **`P0IM-AC-SETTINGS`, `all_match=false`.** Относится только к волатильному
   `modules/3/gate/observed_at`, который различается между любыми двумя вызовами; все сохранённые
   поверхности совпали побайтово.

## 8. Не durable пути доказательств (названы, не переписаны)

1. `evidence/s7accept/matrix-prod.json → meta.json_path/summary_path` указывают на
   `evidence/s7accept/run/result.json` и `run/SUMMARY.md` — **этих файлов нет ни в одном дереве**;
   durable-артефакты: `matrix-prod.json` и `matrix-prod.md` (сводка строится из JSON). Указатели не
   переписаны (артефакт — принятое доказательство, его sha зафиксирован), висячий указатель
   зафиксирован здесь и в `recorded_limits` карты.
2. `evidence/s7accept/prod-snapshot-2.58.194.json` и `evidence/s7accept/visual/**` в этом корне
   отсутствуют (существуют только в ветке `init/meme-s7-accept`, `8d2553ed`); на них ссылаются
   `matrix-prod.json` и визуальные проверки. Для приёмки использованы `matrix-prod.json` (числа) и
   живые кадры 2.58.197.
3. `evidence/S3-OV/**` (скриншоты релизной линии) в этом корне отсутствует; в карте все пути —
   строчные `evidence/s3ov/*`, они существуют. Регистр не ломается, пока никто не добавит
   `S3-OV/…`: на Linux это был бы другой каталог.
4. `evidence/s5b/playwright-visual.json` и кадры S5b в этом корне отсутствуют (упомянуты в
   `binding-e92cdcd5`); привязка S5b опирается на §2 этого документа и живые счётчики.

## 9. Что дальше

1. `P0IM-PB-LLM` (2 строки) — ждёт первой живой LLM-попытки (§5.1); это `WAITING_EXTERNAL`, очередь
   не удерживает.
2. `P0IM-AC-DONE` — свёртка, закрывается сразу после `PB-LLM`.
3. Некритичные находки — в `plans/backlog.md` (дубль подписи «автоматически · автоматически» в
   строке события; формулировка «последние 24 записей процесса»).
