# REL-258179 — выкат QND-NONDET (2.58.179) на production

Дата: 10.11.2026, 00:14–00:40 UTC (12:14–12:40 +12:00). Сервер: `192.255.209.205`,
каталог `/var/www/admin_bot`, unit `admin_bot`.
Результат: **VERIFIED** (обязательные постпроверки пройдены, откат подготовлен).

## 1. DEPLOY_SOURCE

| Поле | Значение |
|---|---|
| Артефакт выкладки | `32e018b939cd8ec453b23e07863fae3be4b683f6`, ветка `release/2.58.179` (в origin) |
| Одобренный кандидат | `629743f9` (ревизор Review: Approved; носитель — ветка базы `6674811f`) |
| Предыдущий прод | `af84b6c68ae253d2f593df4123ff3ca7b72fe65d` (2.58.178, точка отката) |
| `MUTABLE_WORKTREE_REQUIRED` | **no** — выкат из immutable-коммита, локальное дерево не используется |
| Write scope прода | checkout `/var/www/admin_bot` (ветка `release/2.58.179`) + рестарт unit; следы в `/root/deploy-258179/` |
| Схема | **v46 → v47** (первая миграция после 46), аддитивная таблица `semantic_schedule` |

### Cherry-pick в прод-линию (база `af84b6c6`, не `6674811f`)

`bc62da05` → `b29a4a5b`, `46cb550b` → `b8f5a689`, `0cebea92` → `3bce90e5`,
`629743f9` → `0355ac5a`, `c99d64c7` → `dd47d81e` (только evidence-документ,
продуктовых файлов не добавляет).

Конфликты были ровно в 21 файле и только из-за CRLF/LF: прод-линия держит CRLF в
`plans/docs/param-registry-round1025.meta.md` и 20 тестах, ветка кандидата — LF.
Разрешены трёхсторонним слиянием по содержимому с сохранением CRLF прод-линии;
продуктовые файлы среза между линиями байт-идентичны (проверено
`git diff 6674811f af84b6c6` по всем изменённым модулям — пусто).

### Дельта `af84b6c6 → 32e018b9` (106 файлов, срез один)

Продукт: `services/semantic_schedule.py` (новый), `services/quantum_publication.py`
(новый), `services/qnd_diagnostics.py` (новый), `services/nostalgia_worker.py`,
`services/initiative_observer.py`, `services/memory_maintenance.py`,
`services/mca_events.py` (расширение словаря кодов), `services/mca_random_source.py`,
`services/param_catalog.py`, `services/prompt_registry.py`,
`services/status_service.py`, `services/database.py` (шаг v47),
`handlers/summary.py` (событийный сигнал точки живого сообщения),
`web/api/initiative_vitality.py`, `web/app.js` (только блоки quantum),
`web/index.html` (только разметка блоков), `config/settings.py` (APP_VERSION+запись).

Тесты: `tests/test_qnd_*.py` (4 файла), `tests/qnd_fakes.py`, `tests/conftest.py`,
пины каталога/схемы/аудита, `tests/js/*` (паритет), сид-фикстуры расписания в
`test_mod_acl_ux_m2_*`, `test_p0_initfix*`, `test_asap8_v63_b01*`, W5-гейты.

Нет в дельте (важно): `services/direct_capabilities.py`, `services/direct_l1.py`,
`services/direct_execution.py`, `services/direct_chat_service.py`,
`services/access.py`, `services/diagnostic_policy.py`, `web/app.js` вне блоков quantum,
`routes.py`, `bot.py`.

## 2. Прогоны тестов на релизном дереве

| Группа | Итог |
|---|---|
| QND (schedule/publication/event_path/metrics) | **26 passed** |
| nostalgia + observer + memory_maintenance + coordination (16 файлов) | **252 passed** |
| random (mca10a block C, mca10b block A/D) | **50 passed** |
| каталог/схема/миграции/промпты/random (32 файла на финальном SHA) | **722 passed** |
| Полный прогон, релизное дерево | 19 557 passed, 41 skipped, 127 failed, 25 errors |
| Полный прогон, базовое дерево `af84b6c6` (те же 68 файлов) | 86 failed, 21 error |
| Сравнение наборов падений (68 файлов) | **107 = 107, разница в обе стороны пустая** |

Важно про полный прогон: он шёл одновременно с повторным прогоном (моя ошибка),
поэтому часть падений — интерференция двух процессов (общие sqlite-файлы/порты).
Чистое сравнение сделано на 68 файлах, где базовое дерево падает: наборы падений
на базе и на релизе **совпадают побайтово по составу**. Все остальные падения —
предсуществующие дефекты тестов/окружения прод-базы 2.58.178 (summary golden,
webapp UI/JS, youtube-загрузка, budget-меню, `flags.dig_pre_gate_enabled` в
аудите «мёртвых ручек»), они не внесены этим срезом.

Пин-догон (все — под фактический артефакт среза, без ослаблений):
`categorized 580→612`, `REASON_CODES 330→341 (+11 кодов расписания/событий/исхода)`,
`FACTORY_SET_SHA256_12 011c83dfac95→1532c9480cd5`,
`«файлов под аудитом» 315→312` (кандидат пиннился на ветке базы, где под аудит
попадают три файла SELF-DIAG-01 D2, отсутствующие в проде), `хвост миграций 46→47`.
`tests/test_soul1_w5_observer_gates.py` получил ту же прекондицию расписания, что
уже одобрена в 4 peer-файлах; все 17 утверждений сохранены.

## 3. Миграция на проде — фактические числа

Снапшот: `/root/deploy-258179/predeploy-258179.db` (VACUUM INTO + read-back),
`sha256 747da798df6f95190e65c256dd326336359e8d154542ffd41ed8e127ce0a70dc`,
1 965 096 960 байт; read-back совпал с живой БД по всем счётчикам и `quick_check`.

| Показатель | До | После |
|---|---|---|
| `PRAGMA user_version` | 46 | **47** |
| `schema_migrations` (строк) | 35 | **36** (+ `47 semantic_schedule_v47`) |
| `semantic_schedule` | нет таблицы | есть: **19 колонок**, PK `(chat_id, mechanism)`, индекс `(mechanism, next_due_ts)` |
| Строк в `semantic_schedule` | — | **2** (обе — `nostalgia`; backfill не выполнялся, строки созданы первым draw) |
| `PRAGMA quick_check` | ok | **ok** |
| `smart_messages` | 2 077 014 | 2 077 014 |
| `nodes` | 33 755 | 33 755 |
| `edges` | 65 946 | 65 946 |
| `graph_facts` | 24 202 | 24 202 |

Дрейф по четырём таблицам относительно v46-снапшота: **none**. В журнале:
`[database] migration v47: semantic_schedule table ready` +
`applied in 0.0s | semantic_schedule_v47`.

## 4. Health

| Проверка | Значение |
|---|---|
| `/healthz` публично | 200 `{"status":"ok","version":"2.58.179"}` |
| `/healthz` loopback (`:8000`) | 200 `2.58.179` (`:8080` на этом хосте не слушается — проверялся набор портов) |
| unit | `ActiveState=active`, `SubState=running`, MainPID 3568085, `NRestarts=0` |
| старт | `ExecMainStartTimestamp = 2026-11-10 00:21:33 UTC` |
| дерево прода | `HEAD=32e018b9…`, tracked-dirty 0 |
| журнал | traceback/CRITICAL за окно выката нет |

## 5. Наблюдения после выката

1. **Расписание пер-чатово.** Живые строки `nostalgia`: чат `-1004482340693` →
   `next_due_ts 1794283692` (через 13 781 с), чат `-1002661910336` →
   `next_due_ts 1794289072` (через 19 161 с). Интервалы **различаются** между
   чатами, как и требуется контрактом.
2. **Источник draw честный и он квантовый.** В этом окружении ANU **настроен**:
   `source="quantum"`, `provider="ANU Quantum Numbers"`, `fallback_reason=null`.
   Значения: `u=0.45703125` (delay 13 781 с) и `u=0.830596924` (delay 19 161 с),
   draw_id `1944ed27…` и `e0178092…`. Fallback не понадобился.
3. **Витрины честные.** На проде, по живым данным:
   * `nostalgia`: `draws_quantum=1` → `honesty.status_word_allowed=true`,
     `headline="квантовый источник используется"`;
   * `initiative`: `draws_quantum=0` → `status_word_allowed=false`,
     `headline="нет данных: розыгрышей в окне не было"`;
   * слово «работает» отсутствует в обоих случаях (`web/app.js` печатает его только
     при `status_word_allowed`).
4. **Событийный путь — только для своего чата + дебаунс.** На копии прод-БД с
   реальными записями (`DatabaseService`): `request_event` создаёт строку
   `initiative` **только** для целевого чата (`scan_requested_at=1794271197`),
   второй чат не тронут; `due_chats(initiative)=[-1004482340693]`, `due(target)=true`.
   Границы: свежая проверка → `(False,'event_dropped_debounce')`, между дебаунсом и
   полом → `(False,'event_deferred_floor')`, за всеми границами → `(True,'')`.
5. **Шов ностальгии цел, разыгранный интервал не сбрасывается.** `request_event`
   (то, что делает живое сообщение) метит только механизм инициативы:
   `nostalgia_interval_preserved=true` — `next_due_ts` обоих чатов остались прежними.
   Шов `NostalgiaWorker.recall_in_conversation(chat_id, *, now, memory_refs,
   context_rows)` присутствует в выкаченном коде с замороженной подписью и
   вызывается маршрутом `_act_on_memory_recall`; 79 тестов ностальгии зелёные.
6. **Канон чекапа v10.** `services.info_service.INFO_CANON_VERSION = 10` (на
   работающей сборке прочитано значение 10).
7. **DIG pre-gate без потребителей.** `grep -rn DIG_PRE_GATE_ENABLED services
   handlers` → **1** совпадение, и это метаданные каталога
   (`services/param_catalog.py:1798`); в `services`/`handlers` читателей нет.

Не наблюдалось живьём (и не выдаётся за проверенное): строки расписания
**initiative** на проде пока отсутствуют — с момента рестарта в чатах не было
живых сообщений (05:17–05:40 локального времени чата). Механизм при этом проверен
на копии прод-данных: первое живое сообщение вставляет строку (`INSERT … ON
CONFLICT`), после чего идут `due → claim → draw` (получено `u=0.768508911`,
delay 5 672 с, `source=quantum`).

## 6. Откат

- Поведенческий: старый раннер (2.58.178) на схеме 47 видит `current=47`,
  `pending=[]` и **ничего не делает** — проверено локально прогоном старого кода на
  v47-БД: `user_version` остался 47, таблица инертна (старый код её не читает).
- Код: `git checkout -B release/2.58.178 af84b6c6` + рестарт.
- Данные: `/root/deploy-258179/predeploy-258179.db` (v46, `quick_check ok`,
  sha256 в §3). Восстановление — остановка unit, подмена файла, старт.
- Ограничение: down-миграции нет; `semantic_schedule` после отката остаётся
  пустой/инертной таблицей, данные не теряются.

## 7. Что смотреть владельцу в следующие сутки

1. **Ритм по чатам.** Ностальгия должна срабатывать в разные моменты в разных
   чатах (интервал 30 мин – 6 ч, форма зависит от активности). Если оба чата
   «молчат» дольше ~6 ч при живой переписке — это повод посмотреть `Аналитика →
   Инициатива/Ностальгия` (`quantum`): там видно `next_due_ts`, `source`, `u`.
2. **Спонтанные воспоминания.** Ожидаемы редкие уместные отсылки к старой истории
   без прямого вопроса. Частота намеренно низкая: вероятность публикации
   `p` зависит от релевантности/значимости/свежести и «молчание» — норма.
3. **Доля публикаций.** В блоке quantum есть `publications.published/silent/
   deferred` и причины молчания. Если `published=0` при большом числе решений —
   смотреть причины (`semantic_none`, `limits`, `send_recheck`, `random_miss`).
4. **Честность источника.** `source=quantum` при работающем ANU; появление
   `pseudorandom` в `last_draw.source` означает fallback (провайдер недоступен) —
   это не ошибка, но видно в витрине.
5. **Ошибки расписания** в логах: `[qnd] schedule write failed`,
   `event_dropped_busy`, `event_deferred_floor` — первые два повод посмотреть, третий
   штатный.

## 8. Открытые находки (не блокируют выкат, переданы в бэклог)

- `test_cfg03_param_audit::test_visible_dead_knobs_are_exactly_documented` падает
  на `flags.dig_pre_gate_enabled` **и на базе 2.58.178** — расхождение списка
  «мёртвых ручек» с фактическим состоянием (предсуществующее).
- `test_evol018`-пин «файлов под аудитом» до этой волны уже дрейфовал (294 против
  фактических 309) — пин переиздан на фактические 312; текст §5 аудита в
  `plans/features/evol/audit/w2a-evol016.md` исторический, не переписывался.
- `sched.release()` в событийном/тиковом пути инициативы не вызывается: аренда
  строки снимается только `mark_executed`/`mark_missed`, поэтому «холостой» тик
  держит аренду до `limits.qnd_lease_seconds` (300 с при тике 300 с — в проде
  безопасно, но при уменьшении периода heartbeat это ограничит частоту попыток).
