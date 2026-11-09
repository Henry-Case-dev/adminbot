# MOD-ACL-UX-01 M2 — инвентарь хранилищ и runtime-читателей (MAC-S2-102)

Дата: 2026-11-09. Ветка: `integ/unify-release`. Кандидат: M2 поверх `3b1ba3b2`
(этот срез). Документ — приложение к плану (сам план не редактируется из
реализационного дерева).

## 1. Хранилища (второго нет)

| Слой | Носитель | Кто владеет | Что здесь лежит |
|---|---|---|---|
| Глобальные значения | `bot_settings` → `ConfigCache` (`hot.get`) | `services/config_cache.py` | глобальный дефолт каждой настройки |
| Чатовые значения | `chat_profiles.chat_params` (v-1: `overrides`, `gates`, `keys`, `perm_overrides`, `meta`) | `services/chat_params.py` | явный выбор чата; отсутствие ключа = INHERIT |
| Согласие на opt-in | `chat_profiles.gates_opt_in` (колонка) | `services/feature_gates.py` | участие чата в тяжёлых фичах (не veto) |
| Техническая готовность | код/`settings` (env) + провайдеры | владелец capability | ось `ready`, в хранилище не пишется |
| Runtime-реестр способностей | in-memory (`services/capability_registry.py`) | SOUL-1 W10 | диагностика tool-capability, не писатель настроек |

Ни одного нового хранилища, таблицы или «второго ключа» M2 не вводит
(`MAC-S0-08` подтверждён отдельно).

## 2. Канонический слой (единственная семантика)

`services/chat_params.py`:

* `resolve_capability()` — чистое ядро (INHERIT/ON/OFF, `desired`,
  `source`, `emergency_block`, `ready`, `authorized`, `observed`,
  `reason_code`);
* обёртки с чтением стора: `resolve_param_capability` (домен
  `overrides`), `resolve_gate_capability` (домен `gates`),
  `resolve_module_capability` (реестр модулей);
* синхронные точки чтения: `read_override`, `read_global`,
  `read_override_sync` (для sync-потребителей);
* `blocks_side_effect(state)` — единственное правило «нельзя
  публиковать/применять» перед пользовательским side effect.

## 3. Runtime-читатели: кто решает через резолвер

| Потребитель | Что решает | Путь | Статус |
|---|---|---|---|
| `services/feature_gates.py::gates_enabled` / `gate_state` | гейты `chat_params.gates` (dream/nostalgia/lore_auto/permsoc*) | `chat_params.resolve_gate_capability` | канонический |
| `services/feature_gates.py::gate_blocks_publication` | можно ли публиковать (nostalgia и др.) | тот же резолвер, `fresh=True` | канонический (new в M2) |
| `services/permsoc.py::master_enabled` / `master_enabled_global` | мастер PERMsoc | `feature_gates.gates_enabled` | канонический |
| `services/mca_experience_jobs.py::learning_enabled_for_chat` | обучение опыта по чату | `chat_params.resolve_param_capability` | канонический |
| `services/mca_experience_jobs.py::review_enabled` | общий review-job | только env-оси K1/K3 | канонический (shared-ось) |
| `services/lore_worker.py` (`_generate_for_chat_impl`) | авто-лор по чату | `feature_gates.gates_enabled("lore_auto")` | канонический |
| `services/nostalgia_worker.py` (`_process_chat`) | ностальгия по чату | `feature_gates.gates_enabled("nostalgia")` + `gate_blocks_publication` перед отправкой | канонический |
| `services/dream_worker.py` | сон по чату (с fallback мастера) | `feature_gates.gates_enabled("dream", fallback=…)` | канонический |
| `services/initiative_observer.py::chat_observer_enabled` / `chat_capability_state` / `initiative_publish_block_reason` | инициатива (вкл. мем-ветку) по чату | `chat_params.resolve_param_capability("initiative.enabled")` (+ свежее чтение перед публикацией) | канонический (new в M2) |
| `services/meme_initiative.py::_final_gate_reason` | публикация мема (модуль+чат+инициатива) | те же потребительские callables/`_param` | канонический (new в M2) |
| `services/mca_gates.py::memory_*_enabled` | гейты памяти (search/communities/identity/attribution) | `chat_params.get_chat_param` | канонический |
| `services/worker_settings.py::resolve_setting*` | значения воркеров/статуса | `chat_params.read_override` / `read_global` | канонический |
| `services/worker_settings.py::setting_source` | диагностика источника | `chat_params.read_override_sync` | канонический (M2: был приватный `_items`) |
| `services/status_service.py` (снимок модулей) | effective-состояние модулей | `module_registry` + `feature_gates`/`permsoc` | канонический |
| `services/module_registry.py::gate_snapshot` / `registry_for_frontend` | витрина модулей | состояние из `resolve_module_capability` | канонический |
| `web/api/gates.py` (GET/PUT) | гейты чата | `feature_gates.gate_state` / `set_feature_gate` | канонический |
| `web/api/routes.py` (GET/POST `/api/config`) | значения и три-состояние | `chat_params.chat_state` / `resolve_module_capability` | канонический |
| `web/api/cognitive_map.py`, `web/api/memory_overview.py` | веб-поиск памяти | `mca_gates.memory_search_enabled` | канонический |

## 4. In-domain прямые читатели: что исправлено в этом срезе

| Файл | Было | Стало |
|---|---|---|
| `services/worker_settings.py::setting_source` | `getattr(ChatParamsCache, "_items")` | `chat_params.read_override_sync` |
| `services/worker_budget.py::_chat_tz_name` | `getattr(cache, "_items")` + собственный приоритет | `chat_params.read_override_sync` |
| `services/meme_initiative.py::resolve_timezone` | `getattr(cache, "_items")` | `chat_params.read_override_sync` |

Структурный сторож: `tests/test_mod_acl_ux_m2_runtime_edges.py::
test_no_raw_chat_params_cache_readers_outside_resolver` падает, если появится
новый читатель приватного кэша вне `services/chat_params.py`.

Прямых SQL-чтений `chat_profiles` в решающих путях домена нет: `30` найденных
мест — это владельцы профиля (`chat_lore_store`, `feature_gates.has_opt_in`/
`auto_opt_in`, `meme_initiative` ростер чатов, `oversight`, `web/api/access`,
`prompt_release_policy`) и все они читают либо свою колонку, либо `chat_id`,
но не значения настроек в обход `chat_params`.

## 5. Per-chat-параметры, которые читают ТОЛЬКО глобальный слой

Каталог объявляет `471` ключ с `per_chat=True`. Часть потребителей читает
такие ключи через `hot.get` — то есть **чатовый override не применяется**
(поведение было таким до M2 и в этом срезе сознательно не меняется: это
перенос effective-state, а не семантика capability). Перечень по файлам —
полный для решающих путей домена; каждый пункт проверен глазами, не
автогеном:

| Файл | Ключи (семейства) | Оценка |
|---|---|---|
| `services/lore_worker.py` | `limits.lore_*`, `limits.summary_timezone`, `flags.lore_worker_enabled` (мастер джоба) | лимиты/расписание читаются глобально; **гейт** — через резолвер |
| `services/nostalgia_worker.py` | `memory.nostalgia_*`, `limits.summary_timezone` | лимиты/расписание глобально; **гейт** — через резолвер |
| `services/dream_worker.py` | `memory.dream_*` (через `_key` без `chat_id`), `limits.summary_timezone`, `limits.worker_budget_tz`, `flags.belief_decay_enabled`, `flags.persona_enabled` | есть per-chat путь `_key_for` для основных параметров; `flags.belief_decay_enabled` читается глобально |
| `services/memory_maintenance.py` | `limits.graph_*`, `flags.graph_*`, `limits.*_retention_days`, `limits.summary_timezone` | планировщик процесса: границы/расписание — глобальные по контракту |
| `services/status_service.py` | `limits.chat_context_budget_tokens` (через `get_chat_param` — корректно), `flags.download_enabled` (процессный Bot API) | оба читаются в правильном слое |

Это `related-nonblocking` для M2: ни одна из строк не является гейтом
capability, и изменение их слоя — отдельная волна адаптеров (module consumer),
иначе `effective-state` изменился бы без impact report.

## 6. Прямые читатели вне домена M2 (перечислены, не менялись)

| Потребитель | Что читает напрямую | Почему не в этом срезе |
|---|---|---|
| `handlers/alan.py`, `alan_greeting.py`, `common.py`, `direct_chat.py`, `factcheck.py`, `info.py`, `kostik.py`, `search.py`, `slava_presence.py`, `slavik.py`, `summary.py`, `vasya.py`, `video_download.py`, `voice_transcription.py`, `war_alert.py`, `web.py`, `youtube.py` | `hot.get(<per_chat ключ>)` в точках входа handler'ов | домен «ответы/медиа/реакции», не gates/experience/lore/nostalgia/status |
| `services/direct_chat_service.py` | ~53 per-chat ключа (`limits.chat_*`, `flags.chat_*`, `flags.lore_inject_enabled`, `flags.search_enabled`, `flags.webpage_enabled`…) | Direct-контур: большой отдельный контракт контекста/бюджетов |
| `services/tool_router.py` | `flags.dig_enabled`, `limits.dig_*`, `flags.download_enabled`, `limits.download_cooldown` | tool-домен |
| `services/summary_generator.py`, `summary_memory.py`, `summary_xml.py`, `summary_scheduler.py`, `summary_throttling.py`, `summary_test_run.py` | лимиты саммари и graph-RAG | Саммари — отдельный модуль/волна |
| `services/mca_gates.py::random_source_enabled` | `hot.get("memory.random_enabled")` глобально, без чата | модуль «Случайность»: `runtime_gate="global"` в реестре; перевод в per-chat — отдельная волна |
| `services/chat_clock.py` (канонический резолвер пояса) vs sync-потребители `meme_initiative`/`worker_budget` | свой sync-путь пояса | два синхронных потребителя читают **тот же** приоритет; значение сверяется тестом `test_timezone_effective_value_matches_across_consumers`; объединение в один async-резолвер — рефакторинг вне M2 |
| `web/app.js` (UI) | `GET /api/config`, `PUT /gates` | фронт не входит в срез реализации M2; использует серверные `chat_state` |

## 7. Итог

* Решающие пути capability/гейтов домена идут через один резолвер
  (`resolve_capability` + обёртки); второго решателя нет
  (`tests/test_mod_acl_ux_m2_consumers.py::test_no_second_resolver_module`).
* Приватный кэш `chat_params` читается только его владельцем — три прежних
  читателя сведены в `read_override_sync`.
* Все остальные прямые чтения перечислены выше с точной причиной, почему они
  не менялись в этом срезе, и с указанием, что это не гейты.
