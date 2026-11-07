# Deploy 2.58.164 — редактор над клавиатурой + дрейф контрактов 2.58.163

Итог: **deployed и проверено на проде** (192.255.209.205, `/var/www/admin_bot`).
Родительский эпик `hotfix-meme-publication-initiative-ui` при этом **не закрыт**
(см. §7) — этот релиз закрывает только два одобренных фикс-коммита.

## 1. Источник деплоя

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.164` = `8aada85edbd57c5437372b99566ac17ac89047ec` |
| Кандидат (продуктовые коммиты) | `19c3194d` (parent `4c943384`, parent `e4b97ce5`) |
| Предыдущий прод | 2.58.163 @ `e4b97ce5`, healthz 2.58.163 |
| MUTABLE_WORKTREE_REQUIRED | **no** — деплой по неизменяемому SHA; рабочее дерево сервера после checkout чистое (`dirty_after=0`, единственный untracked — `.cache/`) |
| Repo write scope релиза | `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, 28 пин-файлов (24 py + 4 js) |

Покрытие дельты `e4b97ce5..19c3194d` (проверено `git diff --stat`): ровно два коммита —
`4c943384` (мёртвая иконка `arrow_back`, токен `--radius-lg`, пины хвоста схемы 43,
фикстура metafact `status='confirmed'`) и `19c3194d` (фикс высоты редактора + новое
evidence `w11-editor-keyboard-geometry.json`). Ничего постороннего в дельте нет.
Bump-коммит `8aada85e` версию только поднимает (31 файл / 32 вхождения, как в
предыдущих релизах).

## 2. Преддеплойная проверка на кандидате `19c3194d`

| Проверка | Команда | Результат |
|---|---|---|
| Контракты изменённых поверхностей | `pytest tests/test_font_subset.py test_metafact_penalty_round1018.py test_evol014_meme_initiative.py test_evol016_prompt_journal_v39.py test_ur_c_sched.py test_webapp_evol_w11_controls.py test_webapp_back_button.py test_webapp_design_tokens_round1025.py test_evol017_prompt_history_ui.py` | **207 passed, 1 failed** (предсуществующий — §3) |
| Память/графы (smoke) | `pytest tests/test_memory_identity.py test_memory_identity_migration.py test_graphrag_memory.py test_graphrag_database.py test_mca07_retrieval_context_round1027.py test_evol009_memory_diagnostics.py` | **344 passed** |
| JS-пины (агрегатор) | `pytest tests/test_webapp_js_unit.py` | **43 passed** |
| W11 node-контракт | `node tests/js/evol_w11_controls_test.js` | `EVOL-W11-CONTROLS-OK` |
| W12 node-контракт | `node tests/js/evol_w12_internals_test.js` | `EVOL-W12-INTERNALS-OK` |
| PVR-04 node-контракт | `node tests/js/prompt_version_card_test.js` | `PVR-S4-CARD-OK` |
| W11 Playwright e2e | `python tools/ui_evol_w11_controls_e2e.py --out <scratch>/w11 --port 8841` | `EVOL-W11-CONTROLS OK`, `fails=[]`, 25 с |
| W12 Playwright e2e | `python tools/ui_evol_w12_internals_e2e.py --out <scratch>/w12` | `EVOL-W12-INTERNALS OK`, 24 с |
| PVR-04 UI e2e | `python tests/ui_prompt_version_card_e2e.py --shots <scratch>/pvr-shots --json <scratch>/pvr-e2e.json --candidate 19c3194d…` | `failures=0 checks=1220`, `PVR-S4-OK`, 244 с |

Геометрия редактора измерена в e2e (совпадает с заявленным ревьюером):
`768x1024` низ поля **628** при видимой **640** (`maxHeight=232px`, до фикса 664);
`390x844` низ поля **491** при видимой **504**; `1280x800` — 619/800 без изменений.

Пины после bump: `pytest` по 24 пин-файлам → **857 passed, 3 failed** (§3), все три
воспроизводятся на `e4b97ce5` и моим релизным bump не вызваны.

## 3. Предсуществующие красные тесты (не из этой дельты)

Все четыре краснеют и на базе `e4b97ce5` (прод 2.58.163), то есть уже были такими в
работающем проде; ни один не относится к изменённому коду:

1. `test_evol017_prompt_history_ui.py::test_editor_page_contains_history_area` — четыре
   устаревших строковых пина старой формулировки PVR-04 (`импортирована`,
   `Применить эту версию`, `Активная версия не изменилась`); в `web/app.js` этих строк
   нет уже на базе. Фактический текст («из кода» и т. п.) — принятый редизайн.
2. `test_mca17c_invariants_round1047.py::test_no_ddl_catalog_ks_tools_delta` — пин хвоста
   схемы `== 42`; схема на базе уже v43.
3. `test_scope_selector_round1025.py::TestReturnGlobal::test_reset_uses_delete_override_endpoint`
   — пин `body.count("this.api(") == 1`, фактически 6; блок `resetChatOverride` в
   `web/app.js` **байт-в-байт** совпадает с базой.
4. `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff` —
   allowlist `web/`-путей сверяется с diff от древнего baseline `pre-round1026-a1`;
   вне allowlist лежат давно выпущенные `web/static/cog-visual.js`, `glass-probe.js` и др.
   Дельта этого релиза в `web/` — только `web/app.js` и `web/static/app.css`, оба в allowlist.

Это дрейф тестовых пинов (не дефект продукта). Не правился: изменение тест-контрактов
принадлежит Builder/Reviewer, в одобренную дельту не входило.

## 4. Деплой

`git fetch --prune origin` → проверка объекта `8aada85e^{commit}` → `git checkout -B release/2.58.164 8aada85e`
→ `systemctl restart admin_bot`. Перед деплоем снят снимок БД
`/tmp/predeploy-258164.db` (1 718 931 456 байт, sqlite backup API, консистентный при
работающем боте). Миграций в дельте нет: DDL = 0.

## 5. Пост-деплойная проверка

| Пункт | Факт |
|---|---|
| Версия | `healthz` локально и публично: `{"status":"ok","version":"2.58.164"}`, HTTP 200 |
| HTTP-поверхности | `/web/` 200, `/api/health` 200, `/healthz` 200 |
| Сервис | `active/running`, `NRestarts=0`, `MainPID 2881851`, процессов бота — 1 |
| Served asset identity | `web/app.js` в чекауте и в отдаче: **2 062 901 байт, sha256 `495d4882…c3050c6`** — совпадает байт-в-байт с кандидатом; подстановка версии касается только HTML (`__APP_VERSION__`, после отдачи placeholder = 0, маркеры `2.58.164` ×17, `2.58.163` — нет) |
| Фикс в отдаваемом ассете | `_ctlFitEditorsToVisibleArea` — 4 вхождения, `arrow_back` — 0, `border-radius: var(--radius-lg)` — 6 в отдаваемом `app.css` |
| Схема | `user_version` **43** до и после (новой миграции не было), `schema_migrations` 32 → 32, `quick_check ok` |
| Журнал | 175 строк с рестарта, `Traceback` — 0, `ERROR` — 0, `WARNING` — 1 (предсуществующий `embedding generation not serviceable / smart_archive / superseded`) |
| Память | `sqlite-vec loaded (dim=3072, int8=True)`, `embed cache` hits, `graphrag rebuild: resume ticker started period_s=900` |
| UI | публичная загрузка `/web/` (Playwright, 1280×900): 200, title «AdminBot — Админка», версия `2.58.164` в DOM, **0 ошибок консоли**, честный гейт «Миниапп открыт без Telegram-контекста»; снимок — `deploy-2.58.164-prod-web-1280.png` |

## 6. Откат

- Предыдущий прод: `e4b97ce5` (2.58.163) — `git checkout release/2.58.163 && systemctl restart admin_bot`.
- Назначенная точка отката: `8af1b10a` (2.58.162) + бэкап данных.
- Снимок БД перед деплоем: `/tmp/predeploy-258164.db`.
- Схема не менялась (v43), поэтому откат чисто кодовый; `mca_entity_canonical` (v43)
  старым кодом не читается.

## 7. Что осталось непроверенным / вне этого релиза

- **Родительский эпик не DONE**: `requirements_gate.py check --stage release` по
  `hotfix-meme-publication-initiative-ui/requirements-map.json` → `errors=84`
  (строки `HMF-UI-01..07` в PENDING). Карта привязана к старой candidate `ab662a75`;
  перевязка строк — работа PM/Orchestrator, не DevOps. Релиз этого не отменяет.
- Публичный HTTPS проверен по имени `admin-bot.duckdns.org` (Caddy → 127.0.0.1:8000).
  Прямой `https://192.255.209.205/` не отдаёт TLS (нужен SNI/домен) — это не дефект релиза.
- Живое поведение редактора в реальном Telegram-клиенте владельца (клавиатура на
  реальном устройстве) — `owner_optional`, стоячее правило PET_PROJECT, релиз не держит.
- Четыре предсуществующих красных теста (§3) — отдельная задача Builder: обновить
  устаревшие пины под принятый текст PVR-04 и хвост схемы v43.
