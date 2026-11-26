# MOD-ACL-UX-01 M1-C — choke point для ТЕКСТА промпта (дизайн → реализация)

**Дизайн (authoritative):** `plans/features/mod-acl-ux-01/evidence/m1/m1c-choke-point-design.md`
sha256 `612dd9efa7a7aed6a4a54df2641b1f302f5f527a0ac5fda094c4e7443fc8afa9`.
**Предыдущий tip:** `55948c275` (r3: NEEDS_FIXES). **База:** `ffdc6eadf`.
**Роль:** Builder. Ниже — фактическая реализация, швы, покрытие, инварианты, мутации, остаток.

## 1. Механизм (что именно добавлено)

Три части, ровно как в дизайне:

1. **`services/prompt_text.py`** (новый, 213 строк) — `PromptTextDenied`
   (`PermissionError`, `http_status=403`), неизменяемый `TextScope`
   (`kind ∈ {system,global,chat}`, `chat_id`, `view_keys`, `edit_keys`,
   `degraded`), `current/set_scope/reset_scope/use_scope/system_scope`,
   `guarded_key/guarded_keys`, `guard_view/guard_edit/guard_manifest`,
   `build_scope`. Скоуп живёт в `ContextVar`; вне HTTP — `SYSTEM`.
   `build_scope` **переиспользует** канон `web.api.prompt_access.chat_resources`
   (`strict=True`), правило не дублируется; ошибка чтения входов →
   `TextScope(chat, view_keys=∅, edit_keys=∅, degraded="storage_unavailable")`
   (fail-closed).
2. **Стражи внутри владельцев текста.** `guard_view` — перед отдачей текста;
   `guard_edit` — перед записью значения чата; `guard_manifest` — по
   `LayerTrace.block_id` включённых слоёв. Слои без `pg_key` (identity/plan/
   lessons/humor-техники) не гейтятся (код-канон, вне ресурса).
3. **Рантайм для LLM** объявляет `system_scope(...)` на входных функциях
   сборки: `prompt_composer.compose_speech_system`, `compose_machine_system`,
   `direct_chat_service._l2_write_answer`, `mca_authorial_speech.authorial_system`.

### Точные швы (`services/*`)

| Файл | Что сделано |
|---|---|
| `prompt_text.py` | новый модуль (см. выше) |
| `prompt_registry.py` | `_factory_text_impl` + `factory_text` (**guard_view**), `_factory_text_raw` (system scope для метаданных), `factory_chars`; `_effective_prompt_impl` + `effective_prompt` (**guard_view**), `_effective_prompt_raw`; **guard_view** в `core_selection` (`character.core`) и `style_policy_view` (`style.policy`); `registry_view` → `factory_chars` (метаданные без 403) |
| `prompt_composer.py` | `compose_prompt` → **guard_manifest ПОСЛЕ fail-open-ветки** (отказ ACL не проглатывается); `render_layer_texts` → **guard_manifest** (защита в глубину); `compose_speech_system`/`compose_machine_system` → `system_scope` (тонкие обёртки, тело переименовано в `*_impl`) |
| `prompt_release_policy.py` | `_guard_revision` (ключ блока + ambient chat == chat ревизии) в `get_revision_source` и `diff_revisions`; **guard_edit** в `write_prompt_values` (scope=chat), `remove_prompt_override`, `activate_revision` (scope=chat); сравнения/хеши → `pr._factory_text_raw`/`pr._effective_prompt_raw` |
| `chat_params.py` | **guard_edit(key)** рядом с существующим journal-стражем `assert_prompt_write_allowed` (сырой чатовый писатель промпта в обход ACL невозможен) |
| `prompt_factory.py` | `history_for` → **guard_view** (текст истории); `factory_default` → raw |
| `prompt_migrations.py`, `prompt_readback.py` | метаданные/диагностика → raw-варианты |
| `style_policy.py`, `mca_expression.py` | **guard_view** в `effective_policy_sync` (`style.policy`) и `build_expression_settings` (`character.expression`) — эти сервисы материализуют текст документов для preview/UI |
| `prompt_composer.resolve_core_ref` | **guard_view** (`character.core`) — путь preview без документа Core |
| `capability_registry._template_text` | `PromptTextDenied` **перебрасывается** (иначе fail-open вернул бы factory-текст в обход матрицы) |
| `direct_chat_service._l2_write_answer` | `system_scope("runtime_l2_write_answer")` (вызов impl по классу — двойники тестов работают) |

### HTTP-проводка

* `web/api/deps.py::get_tma_user` — после успешной проверки initData строит
  `TextScope` (`X-Chat-Id` → `?chat_id=` → нет) и ставит его;
  `request.state.prompt_text_scope/token`.
* `web/app.py` — pure-ASGI `PromptTextScopeMiddleware` (внешний слой:
  SYSTEM + `reset_scope` в `finally`) и обработчик `PromptTextDenied` → **403**
  `{"detail": <detail>}`.
* `web/api/speech.py` — `_spec_meta` → `pr.factory_chars` (метаданные);
  `except PromptTextDenied: raise` в 4 названных дизайном местах
  (inspector preview, inspector core, `_legacy_history_rows`,
  `_prompt_history_view`) **плюс** `_reraise_prompt_denied(exc)` в 21
  обработчике записи (иначе отказ ACL превращался в 503/409/пустой payload);
  `post_block_rollback` вызывает `guard_edit(key)` **до** разрешения ревизии
  (иначе 404 маскировал бы запрет записи).
* `web/api/prompt_access.py` — `chat_resources(..., strict=True)` для
  `build_scope`; остальное не менялось (это по-прежнему единственный сборщик
  матрицы для HTTP-поверхностей).

**Ничего не удалено как «мёртвое»:** ранние 403 в маршрутах (`_prompt_require_*`,
`_resource_allowed`, `_meme_settings_payload(visible=...)`) оставлены
осознанно — они дают понятный 403 на конкретной поверхности и не дают
GET-витрине упасть в 403 вместо «ключа нет» (design §3.9). Второго источника
истины нет: все они читают `services.access` через `prompt_access`.

## 2. Покрытие (сверка с дизайном §5)

* **r3-блокеры закрыты механизмом, без ACL-кода в маршруте:**
  `POST /api/speech/try` (`effective_prompt` + `core_selection` +
  `style_policy_view`/`effective_policy_sync` + `build_expression_settings` +
  `guard_manifest`), `POST /speech/block/{id}/reset`
  (`remove_prompt_override`/`chat_params.set_chat_params`), `/rollback`
  (`guard_edit` до ревизии + `write_prompt_values`), `POST
  /api/initiative/meme-settings` (`write_prompt_values`).
* **Ранее закрытые пути** (`/api/prompts/*`, `/api/speech/blocks|block`,
  `/speech/core|style|expression`, meme GET, `/api/config`) — без регрессий
  (30-тестовый замок r2 зелёный).
* **Новые поверхности** теперь получают отказ автоматически: любой маршрут,
  переиспользующий `factory_text`/`effective_prompt`/`core_selection`/
  `style_policy_view`/`compose_prompt`/`get_revision_source`/`history_for`,
  в чатовом скоупе спрашивает страж. Обход возможен только сырым чтением
  (`ConfigCache.get`/`chat_params`) — такого в `web/` нет, появление ловится
  инвариантом A (маркер в теле) и AST-инвариантом (импорт сырых
  материализаторов из `web/**`).

## 3. Инвариант A/B (поведенческий, `app.routes`)

Тест: `tests/test_mod_acl_ux_01_m1c_prompt_text_invariant.py::test_no_response_returns_denied_prompt_text`
(+ `test_default_matrix_shows_the_marker`). Эта версия FastAPI держит
`include_router` ленивыми `_IncludedRouter`, поэтому таблица маршрутов
разворачивается через `include_context.prefix` + `original_router.routes`
(плоский список **262 маршрута**, 258 `/api/*`; ручного списка текстовых
эндпоинтов нет).

* **Отравление:** маркер `M1C-CHOKE-MARK` во все guarded-ключи
  (`prompts.*` без `prompts.summary_cover_style_id`, документы `character.core`,
  `character.expression`, `style.policy` с корректными структурами), маркер в
  глобальном слое `cache.get` для guarded-ключей, маркер в ревизии журнала.
  Актор — `local_admin` чата с `section.content` + `edit_persona`.
* **Прогон A (матрица `view_roles=[]`, `edit_roles=[]` для всех guarded-ключей):**
  258 тел ответов, **ни одного маркера**. Санити-проверка «> 50 тел» в тесте
  (иначе отсутствие маркера тривиально).
* **Прогон B (дефолтная матрица):** маркер обязан присутствовать на перечне
  §5 — проверяются `try`, `blocks`, `block/{id}`, `core`, `style`,
  `expression`, `inspector`, meme GET, `/api/config`, `prompts/revisions/{id}/source`.
  Все 11 — с маркером (иначе тест падает как «вакуумный»).
* **Исключены одинаково в A и B** (не отдают текст, но меняют процесс):
  `/api/control/*`, `/api/summary/test/*`.

## 4. Инвариант структурный (AST)

`TestStructuralInvariants`:

* `web/**` не импортирует `system_scope`, `_factory_text_raw`,
  `_effective_prompt_raw`, `journal_write_scope`;
* `compose_speech_system`, `compose_machine_system`, `_l2_write_answer`,
  `authorial_system` содержат вызов `system_scope(`;
* в телах `factory_text`, `effective_prompt`, `core_selection`,
  `style_policy_view`, `compose_prompt`, `render_layer_texts`,
  `get_revision_source`, `diff_revisions`, `write_prompt_values`,
  `remove_prompt_override`, `history_for` есть соответствующий вызов стража.

## 5. Мутации (файлы восстановлены побайтово, git-blob совпал)

| # | Мутация | Результат | Убийца |
|---|---|---|---|
| M1 | убрать `guard_manifest` из `compose_prompt` | **KILLED** | `TestGuardSeams::test_compose_prompt_manifest_guard` + AST-пин |
| M2 | убрать `guard_view` из `effective_prompt` | **KILLED** | `TestGuardSeams::test_effective_prompt_guard` |
| M3 | убрать `guard_edit` из `write_prompt_values` | **KILLED** | `TestGuardSeams::test_write_prompt_values_edit_guard` |
| M4 | механизм целиком: `guard_view`/`guard_edit` → no-op | **KILLED** | **инвариант A**: утечка маркера в `POST /api/speech/style/preview` и `GET /api/speech/inspector` |
| M5 | три стража одновременно (M1+M2+M3) | SURVIVED в A | честно: A ловит **утечку**, а не «какую строку удалили»; при слоистых стражах одиночные/парные удаления маскируются соседними (их убивают точечные seam-тесты) |

## 6. Числа

| Набор | База `ffdc6eadf` | Кандидат |
|---|---|---|
| Замок r1/r2 (30 тестов) | (r2: 30 passed на ветке) | **51 passed** (30 + 21 choke-point) |
| Инварианты + seam (новый файл, 23 теста) | — (модуля нет) | **23 passed** |
| Набор 49 файлов (prompt/ACL/UI/speech/meme) | 16 failed / 1126 passed (из них 6 — артефакты оверлея: 4 `plans/features/**`, 2 inventory без `.deploy`) | **10 failed / 1206 passed** — те же 10 пре-существующих |
| Широкий UI/config (84 файла) | 58 failed в 26 файлах (56 идентичных + 2 артефакта оверлея) | **56 failed / 2101 passed** (идентичны базе) |

Те же 10 пре-существующих: `test_evol018` (пин 323→328), `test_prompt_field_audit`
(`direct.base.synthesizer`), 4 × `test_initiative_speech_layers_chat_overrides`
(двойник без `_writer_evidence_capacity`), 3 ×
`test_soul1_composer_parity_off` (эталон без `_TIME_ZONE_LEGEND`), 1 ×
`test_soul1_registry_completeness` (пин строки `lore_worker.py:709`).

## 7. Остаток (честно)

* **Глобальный скоуп `GET /api/config`** — by-design граница (значения
  промптов не секреты; поведение не менялось). Следствие названо прямо:
  чатовый зритель, опустив `X-Chat-Id`, видит глобальные значения — это
  отдельная строка, не этот corrective (design §8.1).
* **Чат из неизвестного источника** (путь/нестандартное поле тела) даёт
  `global` → текст как раньше. `_chat_scope_id` знает `X-Chat-Id` и
  `?chat_id=`; иных способов в API нет. Инвариант A подставляет чат всеми
  известными способами; новый способ — предмет ревью.
* **`/speech/inspector` при `edit_persona`**: capability больше не даёт текст
  в обход матрицы (закрыто `guard_manifest`/`guard_view`), но сама capability
  остаётся (кто видит раздел — решает она).
* **Живые записи `chat_params`/`param_permissions`** не упражнялись (двойники
  дают 409/503); сквозной путь «изменили матрицу в UI → следующий запрос
  скрыл текст» проверен на снимке прав запроса и на существующих тестах
  записи матрицы.
* **Фоновые задачи, стартующие из web** и переживающие запрос: список
  входных точек дизайна (§2 п.3) покрыт; новых `create_task` в этом
  коррективе не добавлено. `asyncio.create_task`/`to_thread` наследуют scope;
  для задач, переживающих запрос, `system_scope` объявляется на входе.
* **`/api/persona*`, `/speech/examples*`, cover/story-промпты, `content.*`** —
  вне ресурса (design §8), не гейтятся.
* **Живой Telegram-клиент/прод** — вне инженерного acceptance (project rule);
  локальный стенд + реальные роутеры/сервисы, двойники только хранилище.

## 8. R4 corrective (r4-review: F01 blocker, F02, F03)

### 8.1 R4-F01 — уже материализованный текст отдавался в обход матрицы

Найденная поверхность: `GET /api/speech/inspector?correlation_id=...` возвращал
`exact.system`/`exact.messages[*].text` из кольца `prompt_composer._provider_calls`
(200 + маркер для `local_admin` с `edit_persona`). Проверка кэшей того же класса
нашла ещё две поверхности в том же ответе и в том же кольце: inspector **без**
`correlation_id` отдавал `sent.system_masked`/`sent.layer_texts[*].text`/
`sent.style.hint_block_masked` из снимка хода (`_manifests`) и `exact.*` из
последнего вызова кольца (`calls[0]`). Блокер был шире одного параметра.

**Решение (одно правило, без второго источника истины):** уже материализованный
текст (снимок хода, кольцо провайдера) не хранит per-key провенанс → матрицу к
нему применить нечем. Такой текст отдаётся только актору, которому матрица не
может запретить ни один ключ (`services.access.can_view_param` → `True` при
`ctx.is_global_admin`) — глобальному админу.

* correlation-режим (явный запрос записи кольца) остальным — **403**
  `PromptTextDenied`;
* обычный ответ inspector остальным — **200 без текста**: `sent.system_masked=""`,
  `sent.user_parts_masked=[]`, `sent.layer_texts[*].text=""`,
  `sent.style.hint_block_masked=""`, `exact.system=""`,
  `exact.messages[*].text=""`; метаданные (chars, revision, checksum, flags,
  writer) и явная причина `text_restricted="global_admin_only_no_key_provenance"`
  сохранены;
* предпросмотр (`preview`) не затронут: он собирается сейчас и проходит стражи
  владельцев (`effective_prompt`/`core_selection`/`style_policy_view`/
  `guard_manifest`), поэтому разрешённой роли текст виден как раньше.

Почему не «гейтить по ключам»: кольцо/манифест хранят уже склеенный `system`
(base+core+style+expression) и `LayerTrace.block_id`, но не pg-key базового слоя
(`channel_canon`) — сопоставление «текст → ключ» из кэша невосстановимо, любая
попытка была бы догадкой. Единственный scope, который нельзя запретить, —
глобальный админ; ограничение точное и проверяемое, а не эвристика.

### 8.2 Инвентарь кэшей «уже материализованный текст»

| Кэш | Что хранит | HTTP-поверхность | Решение |
|---|---|---|---|
| `prompt_composer._provider_calls` (+`provider_calls()`) | `system`/`messages[*].text` реального запроса провайдера | `GET /speech/inspector` (обычный и correlation), `initiative_publications._full_text_evidence` | inspector: текст только глобальному админу, correlation — 403 остальным; publications: только проверка наличия `correlation_id`, текст не возвращается |
| `prompt_composer._manifests` (+`_composer_manifest_store`) | `PromptManifest` (system, user_parts, layers) | `GET /speech/inspector` (`sent`) | текст только глобальному админу; `guard_manifest` вызывается до использования |
| `prompt_composer._last_layers`/`_diffs`/`_turn_refs` | трассы ревизий/диффы внутри композера | нет HTTP-поверхности | внутренние вычисления, текст не сериализуется |
| `direct_l1._turn_trace` | `TurnTraceEntry` с `TurnRequest` (только входящий `raw_text`) | нет потребителя в `web/**` | текста промпта не содержит (вход пользователя) |
| `turn_trace._turns` | трассы хода | `mca_events` | `_TEXT_KEYS` вычищаются в digest (`_scrub`) |
| `web/api/routes.py::_PROMPT_OP_RESULTS` | результат разрешённой записи промптов (ключи/ревизии/reasons/sha) | идемпотентность `POST /prompts/*` | только после разрешённой записи; тела промпта в снимках нет |
| `prompt_registry._FACTORY_TEXTS` | заводские тексты | публичные `factory_text`/`effective_prompt` | доступ только через стражей; `web/**` не импортирует raw (AST-инвариант) |
| `web/api/speech.py::_LEARNING_ERROR_DETAILS` | сообщения об ошибках обучения | `/speech/learning/*` | текста промпта не содержит |

Поиск: `OrderedDict(`/`deque(`/`maxlen=`/`lru_cache`/`_manifests`/
`provider_calls`/`turn_trace` по `services/**` и `web/**`.

### 8.3 R4-F02 — отказ ACL не проглатывается фолбэком

`compose_prompt`: `except prompt_text.PromptTextDenied: raise` **до** общего
`except Exception` — фолбэк остаётся только для настоящих сбоев сборки.
Провенанс фолбэка тоже исправлен: `PromptPlan.base_block_id` (заполняется из
реестра в `compose_speech_system` и в speech-preview) попадает в слой
`channel_canon` `_fallback_manifest`, поэтому `guard_manifest` может отказать и
на фолбэке. Тесты: `TestComposeFallbackDoesNotSwallow`
(`test_prompt_denied_from_compose_is_reraised`,
`test_genuine_failure_fallback_is_guarded_by_provenance`).

### 8.4 R4-F03 — AST-инвариант ловит все формы алиасинга

`TestStructuralInvariants._prompt_text_bindings` — карта `{локальное имя:
каноническое}` для `import services.prompt_text [as X]`,
`from services import prompt_text [as Y]`,
`from services.prompt_text import system_scope [as Z]`,
`from services import <raw>`; `_scan_offenders` общий для обхода `web/**` и
самопроверки. `test_alias_detector_catches_every_import_form` — 7 форм, включая
`as`-алиас и `services.prompt_text.attr`. Пути нормализуются к `/` (Windows).

### 8.5 RED/GREEN R4 (`red-r4-cache.txt`, скрипт `r4_cache_probe.py`)

| поверхность (`local_admin`, дефолтная матрица) | 73c38477b | кандидат |
|---|---|---|
| `GET /speech/inspector` → `sent.system_masked` | 200, маркер | 200, текста нет, `text_restricted` |
| `GET /speech/inspector` → `exact.system` (кольцо) | 200, маркер | 200, текста нет |
| `GET /speech/inspector?correlation_id=` | 200 + маркер | **403** |
| те же поверхности у глобального админа (контроль) | текст | текст |

### 8.6 Мутации R4 (файлы восстановлены побайтово из копии до мутации)

| # | Мутация | Результат | Убийца |
|---|---|---|---|
| M6 | убрать гейт correlation-режима | **KILLED** (2 failed) | `TestInspectorCorrelationMode` |
| M7 | вернуть проглатывание `PromptTextDenied` в фолбэк | **KILLED** (1 failed) | `test_prompt_denied_from_compose_is_reraised` |
| M8 | `allow_cached_text = True` (текст кэшей всем) | **KILLED** (2 failed) | `TestInspectorCachedTextRestricted` |

### 8.7 Числа R4

| Набор | База `ffdc6eadf` | Кандидат |
|---|---|---|
| Замок M1-C | — | **60 passed** (51 + 9 R4) |
| Инварианты + seam | — | **31 passed** (23 + 7 форм алиасинга + correlation-инвариант) |
| Set1 (18 файлов на базе / 20 на кандидате: prompt/ACL/inspector/soul1) | 17 failed / 420 passed (11 общих + 2 inventory + 4 core_doc — артефакты оверлея) | **11 failed / 517 passed** — те же 11 base-identical |
| Set2 (15 файлов composer/style/direct) | 8 failed / 380 passed | **8 failed / 380 passed** (имена совпадают) |
| Set3 (9 файлов prompt-history/registry/webapi) | 303 passed / 1 skipped | **303 passed / 1 skipped** |

Base-identical 11 в Set1: 2 prompt-пина (`test_evol018`, `test_prompt_field_audit`),
`test_p0_llm_transport_258206::test_llm_guard_is_visible_policy_group` (сдвиг
позиции в JS), 3 × `test_soul1_composer_parity_off`, 1 ×
`test_soul1_registry_completeness`, 4 × `test_initiative_speech_layers_chat_overrides`.
Set2: 3 parity + 5 `test_direct_fallback_recompose_asap32`.

### 8.8 Остаток R4

* Снимок/кольцо теперь **не** отдают текст чатовой роли — это осознанное
  сужение диагностической витрины; текст виден в `preview` (собирается сейчас,
  проходит стражи) и глобальному админу.
* Кэш не хранит per-key провенанс; если понадобится отдавать сохранённый текст
  роли с частичными правами, потребуется записывать provenance ключей в
  кольцо/манифест, а не ослаблять это правило.
* Прочие пункты §7 не изменились.
