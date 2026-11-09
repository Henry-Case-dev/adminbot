# NOST-PROACTIVE — выкладка 2.58.178

Артефакт выкладки DevOps. Только факты прогона: поезд, проверка дельты, промпт-пины,
тесты на точном релизном дереве, живой прод, in-process чек-лист, откат.
Секретов нет.

## 1. Что выкачено

| Поле | Значение |
|---|---|
| Версия | `2.58.178` |
| Задеплоенный SHA | `af84b6c68ae253d2f593df4123ff3ca7b72fe65d` |
| Ветка релиза | `release/2.58.178` (в `origin`), на сервере — immutable detached checkout по SHA |
| Предыдущий прод / база поезда | `2.58.177` @ `1a4a9b1b1ba7429d54f8ca651ce9629efcda7f8e` |
| Сервер | `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot` |
| Схема | `user_version=46`, `schema_migrations=35` — **без DDL** (`services/database.py` вне диффа) |
| Мутирующее дерево для деплоя | не требуется |
| Откат | `git checkout --detach 1a4a9b1b` + `systemctl restart admin_bot` + `backups/predeploy-258178.db` |

## 2. Поезд (упаковка)

| Шаг | SHA | Что |
|---|---|---|
| база | `1a4a9b1b` | задеплоенный прод 2.58.177 |
| cherry-pick 1 | `1e5e57ba` | `565093e2` (P1-корректировка проактивной ностальгии), применился **без конфликтов** |
| cherry-pick 2 | `f4bc2594` | `6674811f` (ревью-блокеры: PROVISIONAL-метки, пин REASON_CODES, фабричный отпечаток), **без конфликтов** |
| релиз | `af84b6c6` | bump `APP_VERSION` 2.58.177 → 2.58.178 + 25 version-пинов + F8-meta |

Кандидат собран на линии `9f862b0f`, прод-линия `1a4a9b1b` от неё независима
(`git merge-base` = `adfd0d0c`), поэтому перенос обязателен. Файлы шва на обеих
базах байт-идентичны (`git diff 9f862b0f 1a4a9b1b -- services/nostalgia_worker.py
services/initiative_observer.py services/prompt_registry.py` пуст), поэтому
cherry-pick прошёл без ручного слияния.

## 3. Дельта продукта

`git diff --name-only 1a4a9b1b..af84b6c6` — 9 путей:

| Файл | Роль |
|---|---|
| `services/nostalgia_worker.py` | проактивный кандидат, `related_memory_hints`, `recall_in_conversation`, `_delegate_initiative` |
| `services/initiative_observer.py` | блок `<Related_Memory>`, поле `memory_slot`, шов `_act_on_memory_recall` |
| `services/prompt_registry.py` | метка/печать внутреннего observer-блока + фабричный отпечаток |
| `tests/test_nostalgia_proactive_recall.py` | 9 новых контрактных тестов (новый файл) |
| `tests/test_nostalgia_worker.py` | правки под новый шов |
| `tests/test_p0_followup_nostalgia_ab.py` | правки под новый шов |
| `tests/test_expression_isolation_followup.py` | пин REASON_CODES 325→330 |
| `tests/test_mca10b_random_applications_block_a_round1041.py` | пин REASON_CODES 325→330 |
| `tests/test_p0_prompts_core.py` | пин фабричного отпечатка |
| `config/settings.py`, `plans/docs/param-registry-round1025.meta.md`, 24 теста версии | релизный bump/пины (ниже) |

Полный список путей включает 25 version-пинов (24 файла тестов + meta). **Ни одного**
файла чужих полос: нет `services/direct_chat_service.py`, `services/direct_capabilities.py`,
нет `web/`, нет `handlers/`; `services/database.py` не тронут; схема остаётся 46.

Идентичность одобренному кандидату: содержимое девяти файлов на `af84b6c6`
байт-идентично деревьям `565093e2`/`6674811f`
(`git diff --stat 6674811f af84b6c6 -- <9 файлов>` = пусто).

## 4. Промпт-пины (обязательная фиксация)

`services/prompt_registry.py` изменён:

- блок `internal.initiative_observer` — **внутренний машинный промпт** наблюдателя
  инициативы (`family=internal`, `scope=code`, `ui=code_only`,
  `legacy_persona=False`, `production_kind=registered`, `owner_lane=W5`), текст
  читается из кода `services.initiative_observer.OBSERVER_EVAL_SYSTEM_PROMPT`;
- метка `initiative-observer` → `initiative-observer-memory-recall`, печать
  `f1169884093b` → `108f277a466f`; указатель потребителя `initiative_observer.py:895`
  → `:944`;
- фабричный отпечаток набора: `b4e8b3569ab2` → **`011c83dfac95`**, предыдущее
  значение зафиксировано в истории рядом с константой (`FACTORY_SET_SHA256_12`);
- счёт блоков: **112**, изменён **ровно 1** (`internal.initiative_observer`),
  остальные 111 канонов и все **12** legacy-персон — байт-в-байт (A/B-дамп
  per-block sha12 на `1a4a9b1b` и `af84b6c6`; `seal_integrity()` пуст на обеих);
- `declare_prompt` для этого блока не передаёт `migration=` явно — действует
  дефолт `registered_pending:W3`; «фабричность» здесь означает заводскую ревизию и
  печать (`factory_revision`/`FACTORY_REVISION_SEALS`), а не редактируемый
  пользовательский канон.

Пользовательские редактируемые тексты промптов не менялись: `legacy_persona`-блоки
и все прочие каноны дали те же sha12; доказательство — A/B-дамп, приложенный к
runner'у деплоя.

## 5. Тесты на точном релизном дереве (`af84b6c6`, `.venv`, Python 3.12.0)

| Набор | Релиз | База `1a4a9b1b` |
|---|---|---|
| ностальгия-ядро: `test_nostalgia_proactive_recall` + `test_nostalgia_worker` + `test_p0_followup_nostalgia_ab` | **55 passed, 0 failed** | 45 passed, 1 failed (`TestHotEnable::test_job_registered_at_off_start_and_hot_enable_works`) — теперь проходит |
| ностальгия + MCA09 (13 файлов) | **241 passed, 0 failed** | — |
| наблюдатель/инициатива (11 файлов) | 228 passed, **4 failed** | 228 passed, те же 4 failed |
| память/опыт (41 файл) | 1194 passed, **1 failed** | 8 passed, тот же 1 failed (файл) |
| random-набор (11 файлов) | **145 passed, 0 failed** | — |
| промпты/реестр (40 файлов) | 805 passed, 2 skipped, **3 failed** | 35 passed, те же 3 failed |

Классификация падений — **предсуществующие на `1a4a9b1b`**, воспроизведены на
базовом дереве с теми же ID и теми же текстами утверждений:

| Тест | Наблюдённая причина (одинаково на базе и релизе) |
|---|---|
| `test_initiative_coordination::test_act_on_opportunity_conflict_defers_to_intent` | предусловие сценария конфликта публикаций (`:1429`) |
| `test_initiative_coordination::test_evaluate_phase_precheck_blocks_before_llm` | LLM вызван 1 раз вместо 0 (precheck) |
| `test_initiative_coordination::test_t1_nostalgia_delegated_refusal_sends_nothing` | тот же сценарий отказа делегирования |
| `test_initiative_coordination::test_t5_every_text_send_site_passes_publish_guard` | лишняя send-точка `tools/rlr_live_proof.py:580` |
| `test_speech_p0_a2_memory::TestSelfEchoNotFactual::test_style_anchors_not_broken` | тест-локальный async-мок |
| `test_evol018_prompt_audit::test_grep_audit_counts_are_stable` | пин 294 vs 309 файлов под аудитом |
| `test_prompt_field_audit::test_every_editable_prompt_has_reachable_surface` | `direct.base.synthesizer` (ui=catalog) |
| `test_soul1_registry_completeness::test_registry_consumer_pointers_point_at_real_lines` | устаревший указатель `internal.lore.init: lore_worker.py:709` (observer-указатель релизом исправлен: `:944` = `OBSERVER_EVAL_SYSTEM_PROMPT = (`) |

## 6. Предвыкладочные артефакты

| Поле | Значение |
|---|---|
| Снапшот | `backups/predeploy-258178.db`, `1 873 014 784` B |
| SHA256 снапшота | `92e5070de35e181c24b5cfd87734a6324715132f7afd2be87aa2138f30e14469` |
| Read-back снапшота | `quick_check=ok`, `integrity_check=ok`, `user_version=46`, `schema_migrations=35` |
| Предыдущие снапшоты | `predeploy-258177.db`, `predeploy-258176.db` — сохранены |
| Свободно до выклада | 51 959 MB (`df -m /`) |

## 7. Пост-деплой факты

| Проверка | Наблюдено |
|---|---|
| UTC деплоя | `2026-11-09T20:45:10Z` (старт), рестарт `20:46:01Z` |
| `HEAD` на сервере | `af84b6c68ae253d2f593df4123ff3ca7b72fe65d`, ветка `HEAD` (detached) |
| Рабочее дерево | `tracked_dirty=0` |
| `APP_VERSION` в checkout | `2.58.178` |
| `/healthz` публично | `{"status":"ok","version":"2.58.178"}` — сразу после рестарта и через ~1 мин |
| Сервис | `ActiveState=active`, `SubState=running`, `MainPID=3523445`, `NRestarts=0`, `ExecMainStatus=0`, `ActiveEnterTimestamp=2026-11-09 20:46:01 UTC` |
| Журнал с рестарта | 210 строк, `Traceback=0`, `CRITICAL=0`, `ERROR=0`, `WARNING=1` |
| Содержание WARNING | `services.summary_memory` «embedding generation not serviceable · FTS-only · build pending — source empty» — не пути ностальгии (pre-existing) |
| Схема после рестарта | `user_version=46`, `schema_migrations=35` (DDL нет) |
| Блоб `services/prompt_registry.py` в checkout | `0de3d21324cec182c519f346cff021352a9e51ee` |

## 8. Postdeploy чек-лист (in-process, без отправки в чаты)

Прогон интерпретатором юнита (`venv/bin/python`) в `/var/www/admin_bot`; все
сценарии — на памяти процесса (`DatabaseService(":memory:")`), фейковый бот, ноль
сообщений в Telegram, ноль вызовов провайдера.

| Проверка | Наблюдено |
|---|---|
| `nostalgia_tick` в планировщике | `JOB_ID=nostalgia_tick`, регистрация `JOB_REGISTERED=True`, `JOB_TRIGGER=interval[1:00:00]`, `JOB_NEXT_RUN=2026-11-10 02:46:47+05:00`, `max_instances=1`, `coalesce=True`, `func=_tick`; в живом процессе — журнал `Added job "NostalgiaWorker._tick" to job store "default"` + `NostalgiaWorker started (tick=60min, silence=45min, max_per_day=3, aggressiveness=0.3, flag=on)` (PID 3523445) |
| Гейт ностальгии резолвится | `gate_state(..., "nostalgia")` → `chat_state=inherit`, `source=default`, `global=False`, `effective=False`, `reason=capability_off` для несуществующего чата; в PG `memory.nostalgia_enabled=true` → в живом чате гейт включается глобальным слоем |
| Живое состояние флага | PG `memory.nostalgia_enabled=true`, `layer_a_enabled=true`, `tick=60`, `min_silence=45`, `max_per_day=3`, `quiet 23–8`, `aggressiveness=0.3`; чатовых OFF-override нет (единственная связанная строка — `limits.worker_priority_order`) |
| Шов живого воспоминания | `recall_in_conversation` присутствует, подпись `(self, chat_id, *, now=None, memory_refs=(), context_rows=None) -> dict` |
| Нет подходящей памяти → молчание | `{"status": "skipped", "reason_code": "no_relevant_memory"}`, `sends=0`, `llm_calls=0` |
| Маршрут Observer | `_act_on_memory_recall` присутствует, `_act_on_opportunity` содержит переход `kind == "memory_recall"` |
| Шов Observer без связанной памяти | событие `initiative_memory_recall outcome=skipped stage=memory:none`, `counters={"memory_recall_unavailable": 1}`, `last_decision.skip_reason=no_relevant_memory`, отправок 0 |
| `DIG_PRE_GATE_ENABLED` | потребителей в `services/` — **0**; единственное упоминание `services/param_catalog.py:1768` (текст каталога), поле `settings` живо, `effective=False` |
| Канон чекапа | `services/info_service.py:987 INFO_CANON_VERSION = 10` |
| Фабричный отпечаток на выкаченном билде | `factory_set_fingerprint()=011c83dfac95` = пин `FACTORY_SET_SHA256_12`, `FP_MATCH=True`, блоков 112, `seal_integrity` чист |
| Контрактные тесты на выкаченном дереве | `55 passed in 6.35s` (ностальгия-ядро, запуск на сервере) |

## 9. Гейт требований

Карты требований для этой полосы нет: `plans/features/smart-module-semantic-routing/
requirements-map.json` привязан к предыдущему кандидату `1a4a9b1b` и строк
ностальгии не содержит; прогон `--stage release` по нему остаётся красным
(`inventory=105 manual=155 scoped=137 errors=193`) — это прежняя полоса SMR, не
эта выкладка. Привязка доказательств и `VERIFIED` — работа PM; DevOps карту не
переписывает.

## 10. Откат (готовность)

`cd /var/www/admin_bot && git checkout --detach 1a4a9b1b && systemctl restart admin_bot`
(`git cat-file -t 1a4a9b1b` → `commit`, `git show 1a4a9b1b:config/settings.py` →
`APP_VERSION = "2.58.177"`), данные — `backups/predeploy-258178.db`
(read-back `ok`, v46, sha256 выше). DDL в релизе нет: схема v46 совместима в обе
стороны, откат кода безопасен без восстановления БД.

## 11. Что смотреть в живом чате

1. Бот может **сам** вспомнить старый эпизод посреди обычного разговора — без
   вопроса «а помнишь?». Это ожидаемое новое поведение: наблюдатель видит
   смысловую связь текущей темы с реальной записью долговременной памяти.
2. Если связи нет — бот молчит (без пустых «кстати, раньше…»).
3. Лимиты прежние и не менялись: не чаще 3 раз в день, тишина ≥45 мин, тихие часы
   23–8, пауза 24 ч после остановки, повтор того же эпизода не публикуется.
4. Воспоминание всегда строится из реальных сообщений чата (дата, автор), а не
   придумывается; отсутствие подходящей записи = молчание.
