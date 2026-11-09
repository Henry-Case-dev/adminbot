# M2 — доказательство кандидата `dd52cbf9`: CHAT OFF в полёте, инвентарь потребителей, края §10

Артефакт составлен PM после независимого ревью кандидата `dd52cbf9` (вердикт **Approved**, 0
проваленных строк) и связывает поведенческие строки среза **M2** карты
`plans/features/mod-acl-ux-01/requirements-map.json` с фактически проверенным кодом.

Продуктовый код в этом проходе не менялся, тесты PM не перепрогонял: поведенческий вердикт
принадлежит Reviewer, здесь он зафиксирован построчно — с именами тестов, текстом assertions и
честной границей непроверенного.

Источник требований: `plans/owner_inputs/2026-11-09-mod-acl-ux-01.md` §2.5, §4.2, §10, §11, §12
(строки 96–116, 570–619, 678–686).

## 1. Кандидат

| Что | Значение |
|---|---|
| Кандидат | `dd52cbf93837b0a578a6aee84ffe9767d69870e3` |
| Родитель | `98bc424ef719083b9392a84918bab0af3b87c587` |
| База M2 | `3b1ba3b2c0b3cb69ecdc5fcc0c5cd54ddfc53515` — **ancestor** кандидата (`git merge-base --is-ancestor 3b1ba3b2 dd52cbf9` → 0) |
| Ветка | `integ/unify-release` (в `master` не влит) |
| Сообщение | `feat(acl): MOD-ACL-UX-01 M2 - CHAT OFF в полёте, инвентарь потребителей, края §10` |
| Объём | 22 файла, +2144 / −57 |
| Продуктовые файлы | `services/chat_params.py`, `feature_gates.py`, `initiative_observer.py`, `mca_events.py`, `meme_initiative.py`, `memory_maintenance.py`, `nostalgia_worker.py`, `summary_memory.py`, `worker_budget.py`, `worker_settings.py` |
| Новые тесты | `tests/test_mod_acl_ux_m2_inflight.py` (5 проверок), `tests/test_mod_acl_ux_m2_runtime_edges.py` (14 проверок, включая параметризованный набор legacy-значений) |
| Документы среза | `docs/mod-acl-ux-01-m2-consumers.md`, `docs/mod-acl-ux-01-m2-deploy.md`, `docs/evidence/mod-acl-ux-01-m2/m2-race-e2e.json` + скриншот гонки |
| Развёрнуто | **нет.** `deployed_commit` карты по-прежнему относится к релизу M5L (2.58.172 @ `bee14188`) и к M2 не применяется |

Копии документов среза перенесены в дерево планов байт-в-байт, чтобы привязка была проверяема из
основного checkout (сам кандидат в `master` не влит):

| Копия в планах | Источник в кандидате | sha256 |
|---|---|---|
| `plans/features/mod-acl-ux-01/reports/m2-consumers-dd52cbf9.md` | `docs/mod-acl-ux-01-m2-consumers.md` | `57c1f6b87de3279de2c639a8a962e2b2ef1fc54f3dc7d2c41ecf349b3c90e082` |
| `plans/features/mod-acl-ux-01/reports/m2-deploy-surface-dd52cbf9.md` | `docs/mod-acl-ux-01-m2-deploy.md` | `868e1e3e7c0416c5ef8ebfc767fa993a8a3a88866548a5581d3a9af36dca13e8` |
| `plans/features/mod-acl-ux-01/evidence/m2/m2-race-e2e-dd52cbf9.json` | `docs/evidence/mod-acl-ux-01-m2/m2-race-e2e.json` | `f1499c4af8217f2e2651f51dbeae91ecc34ccb2dbf9ca30502e73c069d103c5d` |

## 2. Вердикт Reviewer

- **Approved**, 0 проваленных строк; замечаний, блокирующих приёмку, нет.
- Одобрены поведенческие строки среза и две документальные (инвентарь потребителей и поверхность
  деплоя).
- Расхождение в арифметике передачи вердикта: в сообщении координатора перечислены **13**
  идентификаторов, а сводка ревьюера говорит о **12** строках. Ниже привязаны все строки, для
  которых в этом артефакте есть проверяемое доказательство по их собственному acceptance.
  **Две строки, которые цитируемые артефакты де-факто покрывают, в список одобренных не входили**
  (`MAC-S10-04`, `MAC-S10-20`) — они оставлены `PENDING` с точными условиями (§5), а не повышены
  «за компанию». Это осознанная осторожность, а не потеря объёма: доказательства для них уже
  существуют и привязываются одной строкой вердикта.

## 3. Неблокирующие наблюдения ревьюера (сохранены, чтобы не исчезли)

1. **Предсуществующий красный тест** `test_evidence_injection_stays_data_not_instructions`
   воспроизведён на **базовом** коммите (`98bc424e`), то есть это не регресс M2 и не дефект среза.
   Владелец дефекта — не этот срез; в леджере M2 он ничего не блокирует.
2. **Нет именованного pytest на гонку смены чата.** Гонка доказана E2E-артефактом
   `m2-race-e2e-dd52cbf9.json` (40 замеров, 0 поздних перезаписей, у смены чата нет «позднего
   ответа», перетирающего выбор), и для этого проекта такой формы доказательства достаточно.
   Если гонка когда-нибудь регрессирует — добавить именованный unit-тест на переключение чата,
   чтобы регресс ловился в обычном прогоне, а не только E2E.

## 4. Построчный леджер привязки

| Строка | Доказательство на `dd52cbf9` |
|---|---|
| `MAC-S2-113` — проверка настройки при создании и перед первым side effect; OFF из устаревшего snapshot не публикует инициативу | `test_text_initiative_off_mid_flight_single_outcome`: реальная SQLite-БД, чат выключается **между** оценкой и отправкой; `bot.sent == []`, `initiative_sent` — ноль, `writer.generate_calls == 1` (результат не дублируется), в payload задания `counters["sent"] == 0` и `counters["capability_blocked"] == 1`, ровно одно терминальное событие `initiative_publication_cancelled` с `reason_code == "capability_off"` и `stage == "capability:off"`. Плюс `test_publish_block_reason_reads_fresh_profile`: прогретый TTL-кэш держит ON, но `initiative_publish_block_reason` читает профиль заново и возвращает `capability_off` — это и есть защита от OFF из устаревшего снимка. |
| `MAC-S2-114` — выключение прекращает новую обработку и публикацию, но сохраняет историю, прошлые ответы и индекс | `test_text_initiative_off_mid_flight_single_outcome`: число строк `smart_messages` чата до и после тика совпадает (`COUNT(*)` не изменился), записанное значение настройки остаётся `initiative.enabled is False`; новых публикаций ноль. `test_meme_off_mid_flight_cancels_publication`: картинка сгенерирована (`generated is True`), но `published is False`, `sent == []`, журнал попытки — ровно одна терминальная строка (`stage=PUBLISH`, `outcome=skipped`), то есть история попытки сохранена, а доставки нет. Индексы в этих путях не пишутся (см. `MAC-S10-15` про живой индекс). |
| `MAC-S2-115` — повторное включение не даёт replay/backfill | `test_text_initiative_no_replay_after_reenable`: первый тик отменяет публикацию при OFF (результат **не** отложен), второй тик уже при ON и **без новых сообщений** завершается `completed` без новой оценки (`llm.calls == 1`) и без отправок (`bot.sent == []`); курсор/дедуп двигаются штатно. `test_deferred_meme_not_published_after_chat_off`: отложенная строка при OFF закрывается терминально без отправки, и `deferred_active_row(...) is None` — «догрузки» при включении не будет. `test_meme_off_mid_flight_cancels_publication` дополнительно утверждает отсутствие отложенного мема (`deferred_active_row is None`). **Граница:** вторая половина acceptance — «догрузка истории — отдельное действие с preview и правами» — в этом срезе не реализуется и не проверяется: такого действия в продукте пока нет вовсе, поэтому неконтролируемого replay быть не может, а сам контрол с preview/правами живёт в UI-срезе (M4C). Строка привязана по своей негативной (проверяемой в M2) части. |
| `MAC-S10-07` — in-flight задача при CHAT OFF завершает уже вычисленное без новых публикаций и дублированных доставок | `test_text_initiative_off_mid_flight_single_outcome` (`bot.sent == []`, `generate_calls == 1`, `counters["sent"] == 0`) и `test_meme_off_mid_flight_cancels_publication` (`provider.calls == [-100]` — генерация ровно одна, `sent == []`, `published is False`): задача доходит до терминального исхода, но доставки и дубля нет. |
| `MAC-S10-08` — выключение одного чата не роняет retrieval у другого и не останавливает общие индексы и пулы | `test_vector_lookup_off_only_for_that_chat`: у OFF-чата нет ни KNN, ни query-embedding; у соседнего чата `vector_search` работает, `calls["knn"] == [CHAT_B, CHAT_B]` на повторном запросе (backlog не заморожен), `mm._vec_available is True`, `_index_generation_ok("smart_archive") is True` — индекс и сервис живы. `test_vector_gate_is_per_chat_not_shared`: `memory_search_enabled(A) is False` при `memory_search_enabled(B) is True` и глобальном `flags.memory_search_enabled is True`. |
| `MAC-S10-15` — CHAT OFF для векторного поиска отключает lookup только этого чата; индекс и backlog других целы | Тот же `test_vector_lookup_off_only_for_that_chat`: OFF-чат обслужен fallback-путём (`fts:<chat>`), KNN и embed для него не вызывались, а второй чат получил `knn:<chat>`; флаг доступности индекса и поколение не менялись. |
| `MAC-S10-19` — до и после смены флагов counters и ledger по chat_id: ноль вызовов отключённого функционала, но не shared-сервиса | `test_runtime_counters_show_zero_for_disabled_chat`: реальная БД, два чата с одинаковым профилем; для OFF-чата `llm.by_chat[A] == 0`, в `bot.sent` нет A, в in-memory журнале нет `initiative_opportunity`/`initiative_sent` по A; при этом shared-скан выполняется (`initiative_observer_scan` в журнале) и соседний чат даёт ровно одну оценку (`llm.by_chat[B] == 1`); после `flush_events` durable-журнал по `chat_id=A` пуст, по `B` — непуст. |
| `MAC-S10-05` — после рестарта процесса, инвалидации кэшей и PG NOTIFY desired/effective совпадают с сохранённым | `test_restart_and_notify_keep_stored_state`: «процесс 1» прогревает кэш и считает состояние; «рестарт» — новый `ChatParamsCache` на том же профиле даёт те же `(chat_state, desired, source)` для значения и для гейта; затем внешняя запись + `invalidate_chat_from_notify` → резолв видит **новое** сохранённое значение (`desired True/ON` для значения, `desired False/OFF` для гейта). Рестарт здесь смоделирован новым кэшем на том же профиле — реального `systemctl restart` в этом артефакте нет (см. §6). |
| `MAC-S10-09` — сохранённые старым путём chat flags не читаются новым UI как inherit; каждая миграция сверена | `test_legacy_stored_flags_are_not_inherit` (параметризовано `True/False/1/0`): все четыре сохранённых формата дают явное `ON`/`OFF` в домене значений и в домене гейтов, а `INHERIT` — только отсутствие ключа. `test_every_legacy_write_path_stores_explicit_bool`: статическая сверка путей записи — `set_feature_gate` пишет `bool(enabled)`, снятие — `gates.pop(feature, None)`, `POST /api/config mode="inherit"` делает `new_overrides.pop(key, None)`, строка `"inherit"`/`null` не пишется; резолвер ничего не материализует. |
| `MAC-S10-14` — «Время» без продуктового тумблера, timezone доступен и применяется во всех consumers | `test_time_has_no_product_toggle`: ни один модуль реестра не имеет `time`/`timezone` в id или `master_param`, `limits.chat_timezone` — тип `str` и `per_chat is True`, `"time"` отсутствует в `feature_gates.ALL_GATED_FEATURES`. `test_timezone_effective_value_matches_across_consumers`: чат A `Asia/Tokyo`, чат B наследует `Europe/Berlin`; `chat_clock.snapshot`, `meme.resolve_timezone`, `worker_budget._chat_tz_name` дают одинаковое значение по каждому чату, снапшот часов не «выключен» (есть `local_datetime` и смещение). |
| `MAC-S10-03` — два параллельных редактирования с устаревшей версией дают 409 без потери записи; двойной клик не порождает два POST | `test_stale_concurrent_edit_is_409_without_lost_write`: первая правка с токеном пишется, вторая с тем же токеном → `ChatParamsConflict` с `current_updated_at` и `conflicting`, сохранено только победившее значение (частичной потери нет), повтор с актуальной меткой дописывает вторую правку без потери первой. `test_duplicate_post_is_idempotent_not_second_write`: дубль того же POST с уже устаревшим токеном даёт `revalidated is True`, история не растёт, значение то же. `test_ui_double_click_cannot_emit_two_posts`: в `web/app.js` есть per-key in-flight guard и `operation_id`. E2E-артефакт `m2-race-e2e-dd52cbf9.json`: `ok: true`, `double_click.posts == 1` с `operation_id: "op-1"`. |
| `MAC-S2-102` — инвентаризация storage и всех runtime readers приложена к плану | `plans/features/mod-acl-ux-01/reports/m2-consumers-dd52cbf9.md` (копия `docs/mod-acl-ux-01-m2-consumers.md` из кандидата): таблица хранилищ (второго нет), канонический слой, 19 потребителей с точным путём решения, три исправленных прямых читателя приватного кэша, перечень per-chat-ключей, которые читаются только глобально (с причиной), и полный список прямых читателей вне домена с причиной не трогать их в этом срезе. Машинные сторожа: `test_consumer_inventory_note_lists_real_modules` (≥8 ссылок на реально существующие файлы) и `test_no_raw_chat_params_cache_readers_outside_resolver` (статический скан `services/*.py`, `web/**.py`, `handlers/*.py` на `getattr(cache, "_items"` и `"__items__"` → список нарушителей пуст, `read_override_sync` существует). |
| `MAC-S0-03` — сохранённые значения, промпты и версии не перезаписываются при деплое; миграции аддитивны, обратимы, mapping доказан | `plans/features/mod-acl-ux-01/reports/m2-deploy-surface-dd52cbf9.md` (копия `docs/mod-acl-ux-01-m2-deploy.md`): `services/database.py` в диффе M2 отсутствует, шага `_migrate_*` и сдвига `PRAGMA user_version` нет (фронтьер 46), новых таблиц/колонок/индексов/сидов нет, `prompt_migrations` не расширялся (17 миграций те же), `PromptWriteItem` не вызывается, `APP_VERSION` в срезе не менялся; деплой — только `git pull --ff-only` + `systemctl restart`, откат — `git revert` кода. Машинный сторож: `test_stage_introduces_no_schema_or_prompt_rewrite` по 12 продуктовым файлам среза (нет `prompt_migrations`, `PromptWriteItem(`, `def _migrate_*`, `_SCHEMA_VERSION_`). `chat_params` v-1 читается как есть, INHERIT не материализуется. |

Сводка: **13 строк привязано**. У каждой `candidate_commit = dd52cbf9`; строки, доказанные
тестами, ссылаются на этот артефакт (`type: test`), а три строки, чьим первичным доказательством
является документ или E2E-артефакт среза, ссылаются на их байт-идентичные копии в дереве планов
(`MAC-S2-102` и `MAC-S0-03` — `type: static`, `MAC-S10-03` — `type: test` для E2E-артефакта).

## 5. Что осталось `PENDING` и при каком условии

Срез `M2` после привязки: **36 VERIFIED**, **18 PENDING** (54 строки).

| Группа | Строки | Точное условие закрытия |
|---|---|---|
| Живые наблюдения (`live_required: true`) | `MAC-S2-81`, `MAC-S2-TT-1…6`, `MAC-S2-AX-05`, `MAC-S2-SHARED-01`, `MAC-S10-01`, `MAC-AC-02`, `MAC-AC-03`, `MAC-AC-04`, `MAC-S15-12`, `MAC-S15-1-01` (15 строк) | выкат кандидата и наблюдение **на задеплоенном SHA**: пять комбинаций truth-table на реальных чатах, «включён · работа не подтверждена» на живом экране, ось `observed` по реальным событиям, shared scheduler при GLOBAL OFF, сохранность значений/промптов/ключей/ролей после деплоя |
| Сводная строка среза | `MAC-M2-01` | закрывается только после всех строк M2, включая живые наблюдения |
| Покрыты цитируемыми артефактами, но **не входили** в список одобренных строк | `MAC-S10-04` | `m2-race-e2e-dd52cbf9.json`: 4 запроса конфигурации при трёх сменах чата, 40 замеров, 0 поздних перезаписей — нужна явная строка вердикта (и, при желании, именованный pytest вместо E2E) |
| | `MAC-S10-20` | `test_deferred_meme_not_published_after_chat_off`: отложенная строка при OFF закрывается терминально, отправки нет, байты удалены — нужна явная строка вердикта |

## 6. Честная граница

- PM тесты не перепрогонял: имена и assertions взяты из дерева `dd52cbf9`, вердикт — Reviewer.
- Кандидат **не развёрнут**; ни одно живое поведение этим артефактом не подтверждено, признака
  «M2 выкачен» не появляется.
- «Рестарт процесса» в `MAC-S10-05` смоделирован новым кэшем на том же сохранённом профиле;
  реального перезапуска сервиса в доказательстве нет — он остаётся за деплойной проверкой.
- Отсутствие DDL/перезаписи промптов (`MAC-S0-03`) — статическое доказательство (диффы + сторожа),
  прогона на прод-сервере оно не заменяет; на проде сейчас 2.58.174, M2 в нём нет.
- `MAC-S2-115` привязана по проверяемой в M2 части (нет неконтролируемого replay/backfill);
  контрол «догрузка истории с preview и правами» в этом срезе отсутствует и относится к UI (M4C).

## 7. Результат gate (main checkout, `--repo .`, кандидат `dd52cbf9`)

```
--stage plan   → stage=plan   inventory=279 manual=99 scoped=0  errors=0
--stage review --slice M2 --candidate dd52cbf9… --repo .
               → stage=review inventory=279 manual=99 scoped=54 errors=18
```

Все 18 ошибок одной категории — `mandatory not ['VERIFIED'] (got PENDING)`: 15 живых строк,
сводная `MAC-M2-01` и две строки, ожидающие явной строки вердикта (`MAC-S10-04`, `MAC-S10-20`).
Ошибок привязки артефактов, `candidate mismatch` и ошибок slice-graph нет.
