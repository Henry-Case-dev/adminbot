# AC11 — postdeploy SELF-DIAG: глобальный ACL промптов + uptime self-diagnosis

- **База:** `b5bb71c7a6e89bbf13de88b6f013725dcf633563` (2.58.252, deployed)
- **Ветка:** `fix/selfdiag-ac11-uptime`
- **Сессия:** `ses_de8af5191ffeXGb8ZeE00Shz6l`
- **Дата:** 2026-11-26
- **Область:** `web/api/routes.py`, `web/api/prompt_access.py`, `services/status_service.py`, `tests/test_selfdiag_ac11_config_uptime.py`
- **Не изменялись:** `services/direct_chat_service.py`, `services/turn_trace.py`, `web/app.js`, DDL/флаги/эндпоинты/продуктовые тексты.

## DEFECT 1 — `GET /api/config` без `X-Chat-Id` отдавал текст промпта любой роли

### Причина
В `get_config` глобальная ветка (`chat_id is None`) фильтровала только
`spec.secret`; ресурсная матрица (`can_view_param`) применялась лишь в
чатовой ветке. Ключи `prompts.*` не `secret`, поэтому `role=user` и
`role=moderator` получали ~4596 символов `prompts.checkup_system_prompt` и
остальные 26 `prompts.*` — паритет с владельцем. Дефект существовал в
`ffdc6eadf` и `d20a7f73` (не регрессия 2.58.252).

### Исправление
- `web/api/prompt_access.py`: `global_resources(ctx, db_overrides)` — тот же
  `ChatResources`, что и в чате, но с пустым `chat_root` (у глобального
  запроса нет `perm_overrides`). Видимость — существующий `ChatResources.visible`
  (`hidden → global admin`, иначе `access.can_view_param` на
  `chat_param_matrix(key, db_overrides, {})`). Второго правила нет.
- `web/api/routes.py`, глобальная ветка: если `prompt_text.guarded_key(key)`
  (`prompts.*`, `character.*`, `style.*` — ресурс MAC-S10-13) и
  `global_access.visible(key)` ложно — ключ не попадает в `items` (как в
  чатовой ветке). Форма ответа не меняется: schema/каталог не трогались,
  меняется только состав `items` для роли без гранта.
- **Non-prompt настройки не сужены:** `limits.*`/`flags.*`/`content.*`/
  `models.*`/`keys.*` сохраняют прежнюю семантику (кроме существующей маски
  секретов). `resource_access` (поверхность `/api/speech/*`) сохраняет
  прежнюю глобальную границу — это отдельная поверхность, не `/api/config`.

### RED / GREEN
RED — чистый архив `b5bb71c7a` (`git archive`, без stash и без второго
worktree), тест-файл скопирован поверх:

```
pytest tests/test_selfdiag_ac11_config_uptime.py -q
3 failed, 4 passed
FAILED ...test_plain_user_gets_no_prompt_value_or_key
        AssertionError: item {'key': 'prompts.summary_narrator_system_prompt',
        'value': 'AC11-PROMPT-MARKER: ...'} is not None
FAILED ...test_moderator_gets_no_prompt_value_or_key
FAILED ...test_uptime_is_non_null_and_matches_status  (uptime=None)
```

GREEN — кандидат:

```
pytest tests/test_selfdiag_ac11_config_uptime.py -q
7 passed
```

Проверяемые утверждения (реальный RBAC/fake PG, значение реально лежит в
`bot_settings`):
- `user` без чата → `prompts.*` нет ни в `items`, ни в тексте ответа;
- `moderator` без чата → то же;
- глобальный админ → значение приходит целиком (`value == PROMPT_TEXT`);
- `moderator` с DB-грантом `{"view_roles": ["moderator"]}` → значение приходит;
- `user` → `limits.checkup_max_symbols` по-прежнему виден (значение 1200);
- чатовая ветка: `local_admin` с дефолтной матрицей видит ключ, с
  `view_roles: ["moderator"]` — не видит (семантика не изменена).

## DEFECT 2 — `/api/status/self-diagnosis`: `runtime.uptime_seconds = null`

### Причина
`web/api/routes.py` вычитал ISO-строку `status.started_at`
(`services/status_service.py` 76/87) из `datetime` → `TypeError`, который
глушился в `uptime_seconds = None`. `/api/status` считает аптайм по
`started_monotonic` и был корректен.

### Исправление
- `services/status_service.py`: единственная точка разбора
  `_parse_started_at` (ISO-строка/`datetime` → aware UTC) и
  `StatusService.started_at_dt()`. ISO-контракт `/api/status` не изменён.
- `web/api/routes.py`, `_self_diag_payload`: аптайм считается от
  `started_at_dt()`, а не от строки; `started_at` в JSON остаётся прежней
  ISO-строкой.

### RED / GREEN
RED (архив базы) — `assert uptime is not None` → `assert None is not None`.
GREEN — тот же тест: `uptime_seconds` — непустой `int` (~3600 при
искусственном старте час назад), `abs(uptime - /api/status bot.uptime_seconds) <= 2.0`,
`runtime.started_at == started_at.isoformat()`. Оба значения получены через
реальные обработчики `get_status` и `get_status_self_diagnosis`; у
self-diagnosis подменён только permission-гейт (`diagnostic_policy.decide`),
который данным исправлением не меняется.

## Мутации (обе — RED, восстановление байт-в-байт)

| # | Мутация | Результат | Восстановление |
|---|---------|-----------|----------------|
| 1 | Глобальный guard отключён (`and False`) | `TestGlobalConfigPromptTextACL`: **2 failed, 4 passed** (обе утечки) | SHA256 `routes.py` = `677BEF0B…5719` (совпал) |
| 2 | Возврат вычитания ISO-строки (try/except → `None`) | `TestSelfDiagnosisUptime`: **1 failed** (`None is not None`) | SHA256 `routes.py` = `677BEF0B…5719` (совпал) |

Контрольные хэши после восстановления всех трёх файлов:
`routes.py 677BEF0B…5719`, `prompt_access.py FEEA2535…6BFD`,
`status_service.py 620B9B7C…F2FD`.

## Прогоны (кандидат; каждое оставшееся падение проверено на базе)

| Набор | Результат кандидата | На `b5bb71c7a` |
|-------|--------------------|----------------|
| `tests/test_mod_acl_ux_01_m1c_prompt_chat_acl.py` + `..._prompt_text_invariant.py` + `..._m1_predicate.py` | **124 passed** | — |
| `tests/test_checkup_contract.py` (self-diag) | **41 passed** | — |
| `tests/test_status_service.py` | **43 passed** | — |
| `tests/test_acl_global_admin_role_permission_gate.py` + `tests/test_prompt_readback.py` | **95 passed** | — |
| `tests/test_global_config_optimistic_round1025.py` | **5 passed** | — |
| `tests/test_asap8_v6_d07_overrides.py` | **11 passed** | — |
| `tests/test_diagnostic_probes.py` | **70 passed** | — |
| `tests/test_mod_acl_ux_m4c_acl_hardening.py` | **63 passed** | — |
| `tests/test_mod_acl_ux_m2_runtime_edges.py` | **17 passed** | — |
| `tests/test_asap8_v6_c06a_status_ui.py` | **5 passed** | — |
| `tests/test_asap5_random_bootstrap_config.py` | **5 passed** | — |
| `tests/test_prompt_field_audit.py` + `test_asap7_module_completeness.py` | 29 passed, **1 failed** (`test_every_editable_prompt_has_reachable_surface`: `prompts.direct_chat_synthesizer_system_prompt` вне каталога) | **тот же 1 failed** |
| `tests/test_mod_acl_ux_01_m4_module_params.py` + `..._m4_catalog.py` | 15 passed, **1 failed** (`test_js_fixture_matches_live_contract` — устаревший fixture) | **тот же 1 failed** |
| `tests/test_status_section_ui_merge_round1019.py` | 6 passed, **1 failed** (`test_mode_version_line_removed`) | **тот же 1 failed** |
| `tests/test_deploy_identity_d4c.py` | 5 passed, **17 failed** (git/OSError среда прогона) | **те же 17 failed / 5 passed** |

## Технические проверки

- `python -m py_compile web/api/routes.py web/api/prompt_access.py services/status_service.py tests/test_selfdiag_ac11_config_uptime.py` — OK.
- `git diff --check` — OK.
- `git status --porcelain` после коммита — пусто (tracked tree).

## Ограничения / что не проверено

- Нет живой Telegram-сессии: запросы шли через `TestClient` с реальным
  `X-Telegram-Init-Data`-HMAC и тем же RBAC-слоем; реальный прод не
  запрашивался (деплой запрещён заданием).
- Uptime сверяется с допуском 2 с: `/api/status` использует `monotonic`,
  self-diagnosis — wall-clock от `started_at`; при штатном NTP они согласованы,
  при скачке часов возможен разрыв (тип-дефект устранён, источник времени
  прежний).
- Глобальная поверхность `/api/speech/*` (`resource_access`) осознанно не
  сужена — вне дефекта и вне write-scope; это отдельная поверхность.
