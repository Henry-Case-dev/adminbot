# MOD-ACL-UX-01 M4C C3 — реализация (2.58.234)

- Кандидат: ветка `feat/mod-acl-m4c3`, база `f232a3a30a79c074fc3d7fa75d8aa947720d76a4`
  (2.58.233). Внутренние коммиты: **C3a backend** (SHA в `git log`), **C3b UI/evidence**
  (этот коммит).
- Контракт: `evidence/m4c/c3-contract-2026-11-22.md` (master `09e62ff7a`).
- C2 `services/access_preview.py` **не изменялся** (байт-идентичен base).
- C1/C2 `data-*` и preview-поверхность сохранены; новых write в preview нет.

## C3a — backend

| Файл | Изменение |
|---|---|
| `services/pg_db.py` | DDL 1: CHECK `chat_lore_history.field` += `'access'`; `DROP IF EXISTS`+`ADD` (идемпотентно), таблиц/колонок/индексов нет, SQLite schema 48 |
| `services/acl_audit.py` | **new**: `build_event/serialize_event/insert_access_audit/parse_event`, allowlist `v/entity/op/role_name/telegram_id/key/before/after`; `permissions_snapshot/diff`; никаких значений/prompt/last4 |
| `services/config_cache.py` | транзакционный audit для `upsert_admin/remove_admin/upsert_role/delete_role/rename_role`; audit-ошибка → rollback → `ConfigCacheUnavailableError` (503) |
| `services/roles.py` | `role_revision()` — pure sha256 канонического объекта (sorted permissions, role_type, is_custom) |
| `services/access.py` | глобальная матрица: `updated_at` чтение, `expect_absent/expected_updated_at` (CAS), audit `param_global` в одной транзакции; legacy diag-путь без audit/токенов сохранён |
| `services/chat_params.py` | **new** `set_perm_override` — одна транзакция: `SELECT … FOR UPDATE` → CAS/`expect_absent`/merge только ключа → `UPDATE` → `NOTIFY` → audit `param_chat`; после commit invalidate кэша; `ChatProfileAbsent/PermOverrideAbsent/OverrideExists`; no-op без записи |
| `services/chat_lore_store.py` | `history(..., exclude_fields=('access',))` — фиксированный allowlist, фильтр в SQL |
| `web/api/access.py` | per-item `updated_at`; PUT/DELETE токены + 409; атомарный chat POST + **new** DELETE; **new** `GET /api/access/audit`; `access`-строка для chat_admin grants |
| `web/api/routes.py` | `revision` в GET /api/roles; POST `expected_revision/create_only` → 409 `role_exists/role_absent/revision_mismatch`; DELETE/rename токены; audit roles/admins; recheck в `_write_chat_overrides_with_retry` + 2 call-site |
| `web/api/chat_lore.py`, `services/oversight.py` | `field='access'` исключён из lore/oversight-таймлайна |
| `config/settings.py`, тесты | `APP_VERSION=2.58.234`, 24 version-pin файла; F8 re-pin B07/F11 с NOTE |
| tests | `test_acl_audit.py`, `test_webapp_access_write_safety.py`, `test_acl_legacy_inventory.py`; C2 write-count 9→10 с NOTE; `test_webapp_api` fake получил реальное param-permissions хранилище |

### API-формы (frozen)

- 409 роли: `{code:"conflict", reason:"role_exists|role_absent|revision_mismatch", current_revision, current:{permissions,role_type,is_custom}|null}`.
- 409 матрицы: `{code:"conflict", reason:"override_exists|override_absent|revision_mismatch", current_updated_at, current:{view_roles,edit_roles}|null}`.
- 409 chat override: `{code:"conflict", current_updated_at, conflicting:[key]}` (только ключ, без значений).
- 404 чата: `{code:"chat_profile_absent"}` / `{code:"override_absent"}`.
- Audit: `{scope, chat_id, items:[{id,created_at,changed_by,entity,op,role_name,telegram_id,key,before,after,malformed?}], has_more}`.

## C3b — UI/evidence

| Файл | Изменение |
|---|---|
| `web/app.js` | matrix draft/save (`matrixDraft`, `matrixSaveBusy`, `matrixSeq`, per-item статусы, 409-карточка + reapply/accept-server, discard); role `revision`/409/`saveBlocked`; audit-панель 50→200 + entity; local overrides reset; `errText()` для object-detail; generation-guard |
| `web/index.html` | save bar (`data-matrix-savebar`, `data-matrix-save`), 409 (`data-matrix-conflict`, `data-matrix-reapply`), audit (`data-access-audit-panel`), role conflict (`data-roles-conflict`), local block (`data-local-param-overrides`, reset); C1/C2 якоря не удалены |
| `web/static/app.css` | savebar/audit/конфликт, mobile stack/touch 44, фикс h-scroll матрицы (fixed columns, wrap) |
| `tools/acl_legacy_inventory.py` | read-only JSON-инвентарь + diff с каталогом; legacy не удаляется |
| `tools/ui_mod_acl_m4c3_write_e2e.py` | Playwright 5 viewport: dirty→save, 409/reapply, role 409, audit, reset; 403/503 карточки; скриншоты |
| `tests/js/mod_acl_ux_m4c3_write_test.js` | node: 0 API на toggle, N запросов save с токенами, per-item, 409, generation, role revision, audit, local reset, CSS |
| `tests/test_acl_legacy_inventory.py` | inventory shape/guard-route, `--check` exit 0, runtime не импортирует tools |

## Конфигурация/DDL/rollback

- `APP_VERSION=2.58.234`; schema SQLite **48**; PG DDL — только расширение CHECK.
- Rollback `f232a3a` + restart: расширенный CHECK старому коду не мешает, audit-строки
  остаются; downgrade CHECK не выполняется; данные не теряются.
- F8: `PG_DB_SHA256_B07=469775c2…`, `ROUTES_SHA256_F11=71d837c2…` (route-set не менялся;
  новые GET/DELETE — в `access_router`, F8 сканирует `@api_router`); `PARAM_CATALOG` не тронут.
