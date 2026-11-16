# MOD-ACL-UX-01 M4A wave 1 — релизный кандидат `2.58.210` (без деплоя)

Дата сборки: 17.11.2026. Статус: **assembly done / REVIEW**, production не
трогался, деплой не выполнялся, `VERIFIED` не заявляется.

- Ветка: `release/mod-acl-m4a-2.58.210`.
- Worktree: `WorkspaceData/worktrees/…/mod-acl-m4a-2-58-210-974a5f8ea6d3-cb5948dd`
  (unit `MOD-ACL-UX-01-M4A-W1`, кандидат M4A).
- База/откат: `37f6c76f` (`2.58.209`, previous release / rollback target по
  указанию владельца; production в этой сборке не читался).
- Одобренный кандидат: `9bfc67e5` — Reviewer verdict **Approved for 2.58.210
  release preparation**.
- Bump: `368e3001` (30 файлов / 31 строка версии).

## 1. Линия кандидата

| SHA | Содержание |
|---|---|
| `44d3b6f6` | M4A wave 1: каталог 21 модуля из DTO, shell и CHAT tri-state |
| `bc3ca3de` | fix D1–D10 (review findings) |
| `a6348f8f` | chore: удалён временный e2e probe |
| `7e60e09d` | fix R1–R4 |
| `9bfc67e5` | fix D1–D2 (узкий corrective); **approved candidate** |
| `368e3001` | bump `2.58.209 → 2.58.210` (пины) — **content tip** |

## 2. Bump

- Ровно 30 файлов / 31 строка: `config/settings.py` (APP_VERSION +
  changelog, «Prior 2.58.209»), `plans/docs/param-registry-round1025.meta.md`,
  24 py-пина, 4 JS-пина в escaped-форме `2\.58\.210`, polygon ×2.
- BOM/CRLF сохранены; в `settings.py` прежняя единственная LF-строка
  `APP_VERSION` осталась LF, новый префикс — UTF-8.
- `deploy_v2.9.2.py` не изменялся.

Диапазон `37f6c76f..368e3001`: **68 файлов, +6388/−1849**:
- 40 файлов кандидата M4A: +6357/−1818 (product/test/tools);
- 30 файлов пинов: 31 строка (2 файла пересекаются с кандидатом:
  `config/settings.py`, `plans/docs/param-registry-round1025.meta.md`).

Продуктовые файлы кандидата: `services/module_registry.py`,
`web/api/routes.py`, `web/app.js`, `web/index.html`, `web/static/app.css`.
Файлов БД/миграций, composer, промптов, моделей и планировщиков в диффе нет;
новых endpoint'ов нет.

## 3. Инварианты

- `APP_VERSION=2.58.210`; Settings 472 поля.
- Схема БД: `MigrationStep` 47 (max 47), DDL 0, новых миграций нет.
- Каталог параметров: REGISTRY 645 / GROUPS 121 / `_TAB_BY_GROUP` 119 /
  TAB_RULES 22; `tools/gen_param_registry_round1025.py --check` → `CHECK OK`.
- Новых флагов, миграций, промптов, моделей, composer-правок,
  планировщиков и endpoint'ов нет.
- `deploy_v2.9.2.py` не изменялся; PG-настройки и пользовательские
  настройки этим релизом не сбрасываются.

## 4. Тесты

Полные данные и точные команды: `tests-2.58.210.json`. Кратко (post-bump):

| Набор | Результат |
|---|---|
| Обязательный pytest-набор (M4A/M2/M2.1 + f8 + mca23 + webapp JS unit, 24 файла) | **386 passed, 0 failed** |
| Дополнительно: перепиненные py-файлы (23 файла) | 826 passed, **5 known failed** (4 pre-existing + 1 stale-vs-M4A, закрыт follow-up test-коммитом) |
| Закрытие test-debt hotfix10 | **27 passed** (RED на CSS 37f6c76f подтверждён) |
| JS review / catalog | **75 / 207 проверок**, 0 failed |
| 4 перепиненных JS-файла | 4 passed |
| Полный `tests/js/*.js` | 4 pre-existing fail (те же, что на базе) |
| Playwright 5 viewport | **rc=0, failures=0**, 27 потоков |
| `node --check web/app.js`; `git diff --check` (bump-only `9bfc67e5..368e3001`) | rc=0; rc=0 |

Playwright (свежий прогон после bump): сетка 4/3/2/1/1, высота карточки
162.06; workspace 390: `338/338`, подписи `118/106/111`, 44 px, overlap 0;
320: `268/268`, 44/0; 1440/1280: `235/235` без регрессии; 409 на 390/320:
`rowH=btnH=44`, `visibleHit=true`, POST=1, «Разрешить» → workspace diff +
обе кнопки. Отчёт: `evidence/m4a/shots/m4a-e2e-report.json`.

Известные падения вне обязательного набора (не скрываются):
- 4 pre-existing в `test_tool_coordinator_round1026.py` /
  `test_unified_image_request_round1026.py` — устаревшие epic-scope guards
  (tool canon 18 vs 17, forbidden-path allowlists), воспроизведены на базе
  2.58.209 и зафиксированы в `release-2.58.209/tests-2.58.209.json`;
- 1 stale-vs-M4A: `test_webapp_hotfix10_round1025.py::test_card_limit_kept`
  ожидал снятый M4A `.module-list max-width:1100px`; **закрыт** follow-up
  test-only коммитом (`test_catalog_width_contract`): контракт «нет 1100,
  колонка до 1440, сетка 4/3/2/1, карточка 132–164», RED на CSS 37f6c76f
  подтверждён; продуктовый код не менялся.
- `git diff --check` по всему диапазону `37f6c76f..368e3001` даёт 2
  pre-existing whitespace-замечания одобренного кандидата
  (`tests/js/mod_acl_ux_m4_catalog_test.js:385` пустая строка в EOF;
  `web/app.js:602` trailing whitespace в комментарии); bump-диапазон
  `9bfc67e5..368e3001` чист.

## 5. Манифест

`manifest-dry-run.json`: чистое tracked-дерево, `version=2.58.210`,
`dirty_tracked=false`, `deployed_sha=368e3001…` (content tip),
`previous_sha=37f6c76f…`, `previous_version=2.58.209`,
`release_branch=release/mod-acl-m4a-2.58.210`. `.deploy/` после прогона
удалён; production-файлы не читались.

## 6. Откат

`rollback.json`: цель `37f6c76f` (2.58.209), schema 47, DDL 0, миграций и
изменений данных нет. M2.1 live-строки (per-chat overrides/gates) остаются в
существующих таблицах и читаются кодом 2.58.209; настройки не сбрасываются;
bump-коммит отдельного отката не требует.

## 7. Tip и evidence

- **Content tip** — `368e3001` (bump; весь продуктовый код и тесты M4A).
- **Branch tip** — docs-коммит с этими пятью evidence-файлами и следующий
  test-only коммит закрытия test-debt; продуктовый код они не меняют. SHA
  этих коммитов не может быть указан внутри добавляемых/правимых ими файлов;
  актуальный tip — в отчёте Builder/оркестратора и в
  `origin/release/mod-acl-m4a-2.58.210`.
- Manifest dry-run снят на content tip; деплойный манифест должен записать
  фактический checkout-коммит.

## 8. Ограничения

См. `limitations.md`: нет live TMA, W3 не реализован, desktop tri-state 32 px,
topbar «0 — конфликт» — backlog, 4 pre-existing epic-scope guard-падения
(не M4A). Деплоя и VERIFIED нет.
