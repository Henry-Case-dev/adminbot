# SMR P1 (semantic routing demotions) — выкладка 2.58.177

Артефакт выкладки DevOps. Только факты прогона: поезд, проверка дельты продукта,
тесты на точном релизном дереве, живой прод, in-process чек-лист. Секретов нет.

## 1. Что выкачено

| Поле | Значение |
|---|---|
| Версия | `2.58.177` |
| Задеплоенный SHA | `1a4a9b1b1ba7429d54f8ca651ce9629efcda7f8e` |
| Ветка релиза | `release/2.58.177` (в `origin`), на сервере — immutable detached checkout по SHA |
| Предыдущий прод | `2.58.176` @ `2b7e9c7f` |
| Сервер | `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot` |
| Схема | `user_version=46`, `schema_migrations=35` — **без DDL** |
| Откат | `git checkout --detach 2b7e9c7f` + `systemctl restart admin_bot` + `backups/predeploy-258177.db` |
| Mutable worktree для деплоя | не требуется |

## 2. Поезд (упаковка)

| Шаг | SHA | Что |
|---|---|---|
| база | `2b7e9c7f` | задеплоенный прод 2.58.176 |
| cherry-pick | `0d460d4c` | `9f862b0f` (P1, одобренный кандидат), применился **без конфликтов** (`Auto-merging config/settings.py`) |
| релиз | `1a4a9b1b` | bump `APP_VERSION` 2.58.176 → 2.58.177 + 25 version-пинов (как в предыдущих релизах) |

`git diff --name-only 2b7e9c7f..1a4a9b1b` — ровно 16 файлов P1
(`services/direct_execution.py`, `direct_l1.py`, `direct_chat_service.py`,
`direct_capabilities.py`, `media_readiness.py`, `mca_vision.py`,
`mca_experience_jobs.py`, `mca_style_scope.py`, `evidence_policy.py`,
`config/settings.py`, 6 тестовых файлов) + 25 version-пинов в отдельных файлах.
Ни одного изменения в `services/database.py`, `web/`, `handlers/`, промптах и справке.

## 3. Идентичность продукта одобренному кандидату

- Дерево P1-файлов на релизе **байт-идентично** `9f862b0f`: cherry-pick не потребовал
  ручного слияния, `git diff --stat 2b7e9c7f..1a4a9b1b` = 16 файлов, 627/206 — те же
  цифры, что у исходного коммита (`627 insertions(+), 206 deletions(-)`).
- Причина, по которой кандидат вообще пришлось переносить: `9f862b0f` построен на
  `6fec18d2` (линия, содержащая SELF-DIAG-01 D2 `98bc424e`), а прод-линия `2b7e9c7f`
  D2 не содержит. Ни один D2/ACL-файл в релиз не попал: `git diff --name-only
  2b7e9c7f..HEAD` их не содержит.
- `config/settings.py` — единственный общий файл: авто-слияние сохранило и строку
  `APP_VERSION` прод-линии, и P1-правку блока `DIG_PRE_GATE_ENABLED` (проверено чтением
  итогового файла: комментарий P1 на месте, `DIG_PRE_GATE_ENABLED` остался полем).

Идентичность на сервере (sha256 в checkout): `config/settings.py` `4fd42817…`,
`services/database.py` `4d078c27…` (**тот же blob, что у 2.58.176** — файл не менялся),
`services/direct_l1.py` `6be3faea…`, `services/media_readiness.py` `96224b1c…`.

## 4. Тесты на точном релизном дереве

Python 3.12, `.venv` проекта, локальный прогон в worktree релиза.

| Набор | На релизе | База `2b7e9c7f` | Комментарий |
|---|---|---|---|
| 6 целевых наборов (`test_direct_chat`, `test_p1_semantic_routing_demotions`, `test_asap8_v6_d05_experience`, `test_asap8_v6_wc_direct_d04`, `test_evol_evidence_routing`, `test_mca08_style_form`) | **437 passed, 0 failed** | 403 passed (5 файлов без нового) | 403 + 11 (прирост в изменённых файлах) = 414, + 23 (новый P1-файл) = 437 — ровно числа Reviewer (`parent 403` / `candidate 414`) |
| 6 целевых + 2 пина (`test_round1025_f8_registry`, `test_param_catalog`) после bump | **506 passed, 0 failed** | — | пины версии зелёные |
| Широкий набор direct/vision/nostalgia/lore/experience/style/speech/guard/evidence (121 файл) | **2735 passed, 11 failed, 38 skipped** | **2724 passed, 11 failed, 38 skipped** | наборы падений **идентичны по ID** (сравнение строк `FAILED …` — diff пустой) |

Классификация 11 падений — **предсуществующие на `2b7e9c7f`**, релизом не привнесены
(воспроизведены на базовом дереве с тем же текстом):

| Тест | Причина |
|---|---|
| `test_budget_guardrails_round1024::TestMenuFreeze` (2) | menu freeze: ожидается 15 позиций, в дереве 16 |
| `test_direct_fallback_recompose_asap32` (5) | тест-локальный мок `fb_retries()` без kwarg `sent` vs `services/llm_client.py` |
| `test_nostalgia_worker::test_year_back_candidate_sent` | ожидает «год назад» в сниппете |
| `test_outgoing_guard_round1022::test_every_send_point_is_registered_or_allowlisted` | незарегистрированная send-точка `handlers/meme_command.py` |
| `test_p0_followup_nostalgia_ab::test_job_registered_at_off_start_and_hot_enable_works` | строки job'ов при hot-enable |
| `test_speech_p0_a2_memory::test_style_anchors_not_broken` | `RuntimeError: coroutine raised StopIteration` в async-моке |

## 5. Предвыкладочные артефакты и откат

| Поле | Значение |
|---|---|
| Снапшот | `backups/predeploy-258177.db`, `1 941 712 896` B |
| SHA256 снапшота | `87d75afe032cedc69bc5df7152d850b213b415b08a50ed8fa38490992d961f7e` |
| Read-back снапшота | `quick_check=ok`, `user_version=46`, `schema_migrations=35` |
| Предыдущие снапшоты | `predeploy-258176.db` (1 833 639 936 B), `predeploy-258175.db` — сохранены |
| Объект отката на сервере | `git cat-file -t 2b7e9c7f` → `commit` |

Свободное место до выклада: 53 852 MB (`df -m /`).

## 6. Пост-деплой факты

| Проверка | Наблюдено |
|---|---|
| `HEAD` на сервере | `1a4a9b1b1ba7429d54f8ca651ce9629efcda7f8e` |
| `/healthz` публично | `{"status":"ok","version":"2.58.177"}` (и сразу после рестарта, и через ~1 мин) |
| `APP_VERSION` файла в checkout | `2.58.177` |
| Сервис | `ActiveState=active`, `SubState=running`, `MainPID=3495237`, **`NRestarts=0`**, `ExecMainStatus=0`, `ActiveEnterTimestamp=2026-11-09 18:29:17 UTC` |
| Журнал с рестарта (18:28:37Z) | 238 строк, `Traceback=0`, `CRITICAL=0`, `ERROR=0`, `WARNING=3` |
| Содержание WARNING | 2× `services.mca_events` unmapped reason_code (`experience.fresh_stream_lag`) — из **старого** процесса (PID 3466895, до рестарта); 1× `services.summary_memory` «embedding… FTS-only, build pending — source empty» (новый процесс). Ни одного предупреждения из путей P1 (direct/vision/style/experience/поиск) |
| Схема после рестарта | `user_version=46`, `schema_migrations=35` (DDL нет) |
| `/web/app.js` отданный | sha256 `f91ce8ec1ec6446a6fa9daf034a5df93750b8e31c1401ba5fd930b7b69dcca91` |
| `/web/app.js` в checkout | тот же sha256 — совпадает; и он же был в 2.58.176 → фронтенд не менялся |
| `/web/index.html` | подстановка `?v=2.58.177` — 17 вхождений, `2.58.176` — 0 |

## 7. Postdeploy чек-лист (in-process на выкаченном дереве)

Прогон интерпретатором юнита (`venv/bin/python`) в `/var/www/admin_bot`; ни одного
сообщения в чаты, ни одного вызова провайдера, ни одной записи в БД.

| Проверка | Наблюдено |
|---|---|
| Читатели `DIG_PRE_GATE_ENABLED` в `services/` | **0** (ни одного кода, читающего значение) |
| Единственное упоминание флага в `services/` | `services/param_catalog.py:1768` — текст-описание каталога, значение не читает (см. backlog) |
| Effective-значение флага в процессе | `False` (заводской дефолт), потребителей нет |
| Ностальгическая фраза → автоматический `dig_into_lore` | нет: `hasattr(DirectChatService,'_dig_pre_gate_block')=False`, `_nostalgia_markers`/`_NOSTALGIA_MARKERS_RE` отсутствуют, **вызовов dispatch `dig_into_lore` — 0** (5 упоминаний — только комментарии) |
| Инструмент `dig_into_lore` и capability | живы: `CAPABILITY_TOOLS['historical_search'] = ('dig_into_lore','compile_lore_story')` |
| Текстовый вопрос про картинку без вложения | `is_media_dependent(…)=False` для «что на картинке?», «прочитай скрин», «разбери фото»; `vision_intent(«что на картинке?»)=True` (слова сами ничего не решают) |
| Реальный ход `_prepare_turn_media_evidence` (текст без медиа) | `MediaReadiness(association_status='missing', analysis_status='missing', reason_code='no_target', media_dependent=True, consumer='direct')` — vision-анализ не запущен, честное «цели ещё нет» |
| Позитив vision | `own_media=True → True`; `reply_media=True → True`; обычный чат без медиа → `False` |
| Цитата «отвечай короче» | `is_quoted_message=True`, `parse_directive_request → None` (настройки стиля не меняются) |
| Позитив стиля | «отвечай короче» и «Бот, отвечай короче» → `ParsedRequest(verbosity=short)` |
| Поисковая фраза без команды | «я вчера в интернете видел мем», «как найти мотивацию», «в сети пишут…» → `search=False`, `is_search_command=False`, шаги `[]` |
| Явная команда поиска | «Бот, найди информацию о X» → `search=True`, `is_search_command=True`; capability плана L1 → `['execute_web_search']` |
| Грубая коррекция | `«бля, ты тупой что ли, ты ошибся — я говорил про Петю, а не про Васю»` → `{'class':'correction','confidence':'medium','suspect':'aggression'}` |
| Коррекция без брани | `{'class':'correction','confidence':'high'}` |
| Брань без содержательной формы | `{'skip':'aggression'}` |

## 8. Гейт требований

Не запускался в этой полосе: привязка `candidate`/`deployed_commit` и переиздание
доказательств в `plans/features/smart-module-semantic-routing/requirements-map.json` —
работа PM. Карту DevOps не переписывает и `VERIFIED` не выставляет.

## 9. Откат (готовность)

`cd /var/www/admin_bot && git checkout --detach 2b7e9c7f && systemctl restart admin_bot`;
данные — `backups/predeploy-258177.db` (read-back проверен: `quick_check=ok`, v46).
DDL в релизе нет, схема v46 совместима в обе стороны; объект `2b7e9c7f` на сервере есть.

## 10. Что осталось проверить владельцу (необязательное наблюдение)

1. Обычный разговор с упоминанием прошлого («помнишь, как мы тогда…») — ответ по смыслу,
   без автоматического «исторического» блока.
2. Вопрос про картинку без картинки («что на фото?») — бот не разбирает случайное
   соседнее изображение, а просит прислать/уточняет.
3. «отвечай короче» без кавычек — стиль меняется; «отвечай короче» в кавычках — нет.
4. «Бот, найди …» — поиск работает; «я в интернете видел…» — обычный ответ без сети.
