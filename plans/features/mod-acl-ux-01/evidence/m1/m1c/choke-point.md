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
