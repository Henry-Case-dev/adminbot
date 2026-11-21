# MOD-ACL-UX-01 M4C C1 — implementation / evidence

- База: **`374dc60609986a9250170a34a48c93bf2ba85e29`** (2.58.228,
  `release/mod-acl-m4b3-2.58.228`), schema 48, PG DDL 0.
- Ветка: **`feat/mod-acl-m4c1`** (worktree
  `.../worktrees/.../mod-acl-ux-01-1e46be007668-eaa8504e`, от base, не от master).
- Кандидат C1.1: **`422dbbd38`** — страница/чтение, strict matrix, cold 503.
- Кандидат C1.2: **`de80a6cb9`** — whole-object preservation, superuser
  read-only, editor tests.
- Evidence-коммит: следующий commit этого каталога (`plans/.../m4c/c1/**`).
- APP_VERSION **2.58.228 не менялся**; версия/релиз — отдельно (2.58.229).

## 1. Что закрыто по строкам C1

| req_id | Статус C1 | Факт |
|---|---|---|
| MAC-S0-10 | C1 | Страница вместо модалки; гранулярные права сохранены; `saveRole` не теряет гранты |
| MAC-S4-175 | C1 | 401/403 — карточка причины + безопасная часть `/api/access/me`; 403 ≠ пустая БД |
| MAC-S5-293 | C1 | Все параметры/группы из API: 622/121; count из данных, без хардкода |
| MAC-S5-294 | C1 | 403 отдельной карточкой, не пустой таблицей |
| MAC-S8-501 | C1 (reassign → C3) | Роли/тип/wildcard/custom + «кому назначена» по `/api/admins`; superuser read-only; last-admin/used-role 409 показываются; чатовые гранты — ссылка на `#/access/local`; **новых assign/reassign путей нет** |
| MAC-S8-502 | C1 | 9 CATEGORIES + `access` + `chat_lore`; `chat_lore` из `role.permissions`, не из tree |
| MAC-S8-503 | C1 | 7 фактических `ACTIONS_TREE` + read-only «только владелец» без фиктивных id |
| MAC-S8-504 | C1 | Дерево **Раздел → Модуль → Группа → Параметр**; owner из boot `/api/config.modules` (`_f4Registry`), fallback честный; поиск RU+key |
| MAC-S8-521 | C1 | Клиентские поиск/дерево/collapsed; один основной scroll |
| MAC-S8-522 | C1-часть | Поиск key→owner→состояние; чтение чатового override/preview — C2 |
| MAC-S8-PAGE-01 | C1 | Самостоятельная страница; модалки только confirm/admins/local |
| MAC-S8-PAGE-02 | C1 | Route/deep link/Back; storage не менялся; второго ACL/store нет |
| MAC-S8-LAY-01 | C1 | 220–280 px слева; `minmax(0,1fr)` справа; один scroll; без вложенных скроллеров |
| MAC-S15-09 | C1 evidence | Legacy `param_permissions` не удалялся; авто-миграций/чистки нет |
| MAC-S15-13 | C1-чтение | Видны view/edit и secret-бейдж; negative view≠edit — C3 |
| MAC-S15-1-08 | C1 | Поиск по загруженным данным, 0 запросов на символ |
| MAC-S8-SEC-01 | C1 mobile/errors | 401/403/404/503 разными карточками; секреты не раскрываются; h-overflow 0; negative initData/RBAC — C3 |
| MAC-AC-13 | C1 page | Страница/группы/поиск; «путь разрешения» — C2 |

**Частичные:** MAC-S8-501 (reassign C3), MAC-S8-522 (chat override C2),
MAC-S15-13 (negative C3), MAC-S8-SEC-01 (negative C3).

**Не делалось (C2/C3):** `GET /api/access/effective`, chat
`param_permissions` read/preview, `GET /api/access/chats/{id}/admins`,
dirty/409/audit/revisions, `DELETE` чатового override, revoke-mid-flight,
recheck, leg-инвентарь, S1/S2/S3 (server guards).

## 2. Изменения

| Файл | C1 |
|---|---|
| `web/app.js` | страница/route-состояние, loaders с `global:true` и сохранением статуса, матрица `nav→module→group→param` + owner/поиск, редактор в pane, whole-object save, read-only политика |
| `web/index.html` | roles modal → самостоятельная страница (`data-roles-page`), якоря `#acc-roles-title`/`#sec-roles`/`#sec-matrix`; модалка редактора удалена |
| `web/static/app.css` | сетка 220–280, tabs, дерево, mobile switcher/⋯, touch ≥44, без h-overflow |
| `web/api/access.py` | strict GET матрицы → 503 |
| `services/access.py` | `db_override_map(pg, strict=False)`; strict=True читает PG напрямую и raise; runtime fail-open не изменён |
| `web/api/routes.py` | cold 503 для roles/admins/tree при пустом кэше и `pg_available=false` |
| `tests/js/mod_acl_ux_m4c1_roles_page_test.js` | новый |
| `tests/js/mod_acl_ux_m4c1_editor_preserve_test.js` | новый |
| `tests/test_webapp_access_matrix_read.py` | новый (17 тестов) |
| `tools/ui_mod_acl_m4c1_roles_e2e.py` | новый Playwright + `--serve` для Browser Use |
| `tests/js/evol_glass_seam_test.js` | allowlist: `web/api/access.py` (API, не оптика; protected optics байт-в-байт) |
| `tests/test_webapp_hubs_matrix_ui.py`, `tests/test_webapp_evol_w13_touch_portal.py` | осознанно обновлены modal/старые UI-маркеры |
| `tests/ui_soul1_glass_tiera_e2e.py` | modal-surface `#/access/admins` (роли — страница) |
| `tools/ui_evol_w10_sections_e2e.py` | mobile-матрица: открыть вкладку «Доступ к параметрам» |

Ограниченный scope diff (`374dc6060..HEAD`): только `services/access.py` из
`services config handlers database.py migrations prompts`; DDL 0; новых
endpoint'ов/полей/флагов нет; `/summary`, telegram, `memory_agi.py`,
`progress_scope.json`, `workflow_state.md` не тронуты.

## 3. Ключевые инварианты

- **Strict matrix:** `GET /api/access/param_permissions` при `pool=None`
  или исключении PG → **503**; при рабочем пуле → 200/622; non-global → 403
  до чтения. Runtime `db_override_map(strict=False)` по-прежнему `{}` при
  PG down.
- **Cold read:** пустой RAM-кэш + `pg_available=false` → 503 для
  roles/admins/tree; непустой runtime-снимок → 200.
- **Whole-object:** `saveRole` стартует с полного `role.permissions` из
  `GET /api/roles`; правит только известные узлы; сохраняет `wildcard`,
  пустые `section.access`/`chat_lore`, неизвестные grants и top-level поля.
  `applyTree` не пересчитывает пустую секцию из детей.
- **Политика UI:** superuser (`admin`/`global_admin`/`role_type=global_admin`)
  read-only; non-global — read-only; create/edit/rename/delete — только
  `is_global_admin`; last-admin/used-role 409 — существующие, не обойдены.
- **Owners:** `_f4Registry` из boot `/api/config.modules`; второго запроса
  нет. На стенде 121 группа: 61 owner / 60 fallback; по параметрам —
  ожидаемое 324/298 на полном каталоге.

## 4. Preflight (read-only, без production доступа)

Builder не имеет права ходить на прод (SSH/LLM/прод запрещены вводной).
Проверка выполнена по зафиксированному контракту и seed-коду:

- `services/pg_db.py:630–656`: **4 встроенные роли** (`admin` wildcard,
  `moderator`, `user`, `local_admin`) и **3 назначения** в `DEFAULT_ADMINS`.
- Custom-роли с `section.access`, назначенной не-владельцу, в seed нет;
  production-факт 4/3 зафиксирован контрактом §0.1 / backlog 2026-11-21.
- Живой `SELECT bot_roles/bot_admins` на проде **не выполнялся** — это
  ограничение доступа Builder, не owner QA. Условие §6.4 (появление такой
  роли) проверяется DevOps/Reviewer перед deploy.

## 5. Проверки

- `tests-node.txt`: 2/2 новых node PASS; полный `tests/js` 127/130,
  3 падения воспроизведены на base (не регрессия); B1 **138/0**,
  B2 **92/0**, B3 **131/131** (`regression-b1/b2/b3.json`).
- `tests-python.txt`: focused **276 passed**, новый файл 17 тестов;
  `py_compile` OK.
- `tests-e2e.txt`: `tools/ui_mod_acl_m4c1_roles_e2e.py` **PASS 0 failures**
  на 1920/1440/1280/768/390/360/320 + error-сценарии; `shots/report.json`.
- `browseruse.json`: реальный Chrome, desktop/mobile, switcher/⋯/touch,
  screenshots `browseruse-*.png`.
- `node --check web/app.js` — OK.

## 6. Ограничения / RFL

- Локальный стенд с API-стабами и TMA_STUB, **не live TMA**; production
  данные не мутировались. Живой non-global/local_admin/user/custom-сеанс и
  TMA — **RFL**, не owner QA.
- `requirements_gate.py check --stage plan` не запускался: на release-дереве
  нет `requirements-map.json` (planning-линия не мержится в продукт).
- B3 один раз дал тайминговый `detail_closed` на существующей ленте
  «Опыта»; повтор на том же SHA — 131/131.
- `test_webapp_evol_w10_sections.py::test_live_render_sections_e2e` имеет
  3 pre-existing падения на base; C1 не добавляет новых (проверено base
  vs candidate). Тест перезаписывает `plans/features/evol/audit/evidence` —
  посторонние изменения восстановлены.
- S1/S2/S3 остаются C3. C1 UI-гейт non-global — политика интерфейса, **не**
  серверная граница; C1 этого не заявляет.
- `GET /api/access/chats/{id}/admins`, effective/preview, audit — C2/C3.

## 7. Откат

Ветка не деплоилась. Откат — вернуть `374dc6060`
(`release/mod-acl-m4b3-2.58.228`) + restart; схема/данные не менялись,
поэтому restore БД не требуется. Старые клиенты получают те же API-формы.
