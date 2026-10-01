# Review — HOTFIX `cover-style-save-hotfix` (cover style select → «save failed»)

- **Feature-ID**: cover-style-save-hotfix (dir: `plans/features/hotfix-cover-style-select-save-failed/`)
- **Risk-Level**: R1 (backend-only хотфикс одного роута + тесты; запись в persistent state через принятый контракт chat_params; без миграций, auth-изменений, зависимостей и публичных контрактов за пределами восстановления задуманного поведения)
- **Status: Approved** (Approved for release, деплой 2.58.43)
- **Reviewed-Commit**: `0dc5679a32be6237e58cd17da35a1c33f82ecf9e` (HEAD master; хотфикс — незакоммиченный worktree поверх HEAD, коммит создаётся после гейта по указанию владельца)
- **Working-Tree-Hash**: `1647d9039e6888b219075487d6578158dce00120a6073561622f55df88190994` — SHA-256 детерминированного манифеста (path : SHA-256 контента, UTF-8, `\n`-join) по 4 файлам скоупа хотфикса:
  - `web/api/cover_styles.py` : `8C0D60A20F683302D2AFA41A2392406FB3401D36FE5E6D00695487CF401314D9`
  - `tests/test_cover_styles_contract_asap32.py` : `7AD401557AF5BAA3082CCE4F0F4769EE3EE05EC2AE30C4506DF277C9C052799F`
  - `tests/test_extra_cover_styles_api.py` : `F94C835BBD4F0D810202A2038B3A3DC06C7A12A2E22AC736405038015EA52596`
  - `plans/features/hotfix-cover-style-select-save-failed/evidence.md` : `FAA5B8B00CD4105E6AB4CDD4F4C652CBABA37186E8936F4856B5A230BB4615B7`
  - Вне скоупа (чужой/служебный WIP, не входит в манифест, код не затрагивают): `plans/docs/mca-round1027-arch-frames.md`, `plans/metrics.md`, `plans/workflow_state.md` (modified, bookkeeping Orchestrator'а — в diff присутствует строка статуса хотфикса), untracked `node_modules/`, `package*.json`, `extra_images/`, `.playwright-mcp/`.
- **Spec-Hash**: N/A — в feature-директории нет `spec.md` (хотфикс-флоу). Требованийный артефакт = `evidence.md` (хеш выше, входит в WTH-манифест). Апрув привязан к этой связке.

## Git base и охват изменений

Base: master `0dc5679` (прод 2.008.42-линия, HEAD). Diff worktree vs HEAD проверен построчно:
- `web/api/cover_styles.py` — только тело `cover_style_select` (+29/-4): `pg=_pg(cache)`, read-modify-write через `get_all_chat_params(chat_id, pg=pg)`, патч `{"overrides": merged}`, pop при пустом `style_id`, guard `not root` → RuntimeError → 503. Комментарий HOTFIX 2.58.43 на месте.
- `tests/test_cover_styles_contract_asap32.py` (+121): FakeDB/FakeConn расширены chat_profiles-SQL (SELECT/UPDATE, history, advisory, notify), helper `_put_chat_profile`, новый класс `TestSelectPersistsViaChatParams` (4 теста), стаб `_fake_set(..., **kw)`.
- `tests/test_extra_cover_styles_api.py` (+47): `test_select_per_chat` переписан под реальный контракт (форма overrides + pg= + сохранение чужого override), новый `test_select_clear_removes_override`.
- `web/app.js` НЕ менялся (git подтверждает) — UI-слой вне скоупа.

## Root cause — независимое подтверждение кодом

- **Д-1 (503 всегда)**: `services/chat_params.py:422-424` — `set_chat_params` при `pg=None` → `pool=None` → `raise ChatLorePgUnavailable` → общий `except Exception` роута → 503 «save failed». Прецеденты корректных вызовов: `web/api/routes.py:978-980`, `web/api/access.py:443-447`, `handlers/chat_lifecycle.py:111-116` (все передают `pg=`). Подтверждено.
- **Д-2 (молчаливый drop плоского ключа)**: `chat_params.py:447-450` — мержатся ТОЛЬКО namespaces `overrides/gates/keys/perm_overrides/meta`, `new_root[ns] = dict(patch[ns])` (полная замена namespace); читающий путь `chat_params.py:359-361` резолвит `root["overrides"][key]`. Плоский ключ выбросился бы молча с 200. Подтверждено. Форма `{overrides: …}` + read-modify-write в фиксе — единственно корректная.
- **Guard `not root`**: нюанс — `get_all_chat_params` для ОТСУТСТВУЮЩЕГО ряда возвращает truthy v-1-лейаут (`chat_params.py:398-399` + `_root_with_meta` :221-231), так что guard ловит именно fail-open чтения (pool нет / PG-исключение → `{}`), а отсутствующий ряд даёт 503 через `ChatParamsConflict` в writer'е (`chat_params.py:442-443`). Итог тот же честный 503, запись поверх чужих данных невозможна в обоих случаях. Существующий профиль с пустым params → truthy root → ложных 503 нет. Проверено по коду, дефекта нет.

## Checks performed (все выполнены независимо, не по statements Builder'а)

1. Построчный ревью diff'а трёх файлов vs base + семантика `chat_params.py` (merge/resolve/fail-open) по коду.
2. `pytest tests/test_cover_styles_contract_asap32.py::TestSelectPersistsViaChatParams -v` → **4 passed** (регрессия, сохранение чужого override, очистка, 404 unknown).
3. `pytest tests/test_cover_styles_contract_asap32.py tests/test_extra_cover_styles_api.py -q` → **37 passed**.
4. **RED-on-pre-fix (stash-приём, воспроизведён независимо)**:
   - stash только `web/api/cover_styles.py` (тесты остаются новыми) → `TestSelectPersistsViaChatParams`: **3 failed / 1 passed** (проходящий — `test_select_unknown_style_is_404`: 404-путь до chat_params-вызова, корректно); stash pop — restore проверен SHA-256 (байт-идентично).
   - stash только кода → extra-select: `test_select_per_chat` + `test_select_clear_removes_override` → **2 failed**; restore hash-OK.
5. Полный `pytest -q` → **10437 passed / 2 failed** за 301.85s — ровно ожидание. Падения — якоря `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff` и `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`. Независимо: stash всех 3 файлов хотфикса → якоря **падают и на чистом базисе (2 failed)** — pre-existing, документированный локальный базис (прецедент «полный pytest 10432/2», коммит `1a25d48`); Δ-математика 10432+5 новых = 10437, новых падений 0. Restore hash-OK.
6. F8: `python tools/gen_param_registry_round1025.py --check` → `CHECK OK: реестр 488 == REGISTRY…`, exit 0.
7. Permissions: `/cover/select` = `requires_permission('access')` (`cover_styles.py:345`), 404 до записи при неизвестном стиле, `changed_by=user.id` в аудит-истории.

## Requirement/evidence coverage

| Acceptance (evidence.md) | Проверка | Статус |
|---|---|---|
| Выбор seeded-стиля сохраняется в PG в форме `overrides[key]`, читающий путь резолвит | `test_regression_select_persists_via_chat_params` (real chat_params, без monkeypatch; `_resolve_from_root` + history) | ✅ GREEN, RED pre-fix |
| Чужие per-chat overrides не затираются | `test_select_preserves_other_chat_overrides` + `test_select_per_chat` | ✅ GREEN, RED pre-fix |
| Снятие выбора удаляет override (resolve-чейн DC-5, без хард-пина) | `test_select_clear_removes_override` ×2 (contract + extra) | ✅ GREEN, RED pre-fix |
| Неизвестный style_id → 404 до записи | `test_select_unknown_style_is_404` | ✅ GREEN (pass и pre-fix — по построению) |
| Non-admin может выбирать; admin-мутации — существующие тесты | `test_non_admin_can_list_and_select` (стаб обновлен `**kw`) в составе 37 passed | ✅ GREEN |

## Focused audit coverage

- Интеграционная кромка: роут ↔ `chat_params` ↔ `chat_profiles` (SQL-контракт FakeConn отражает реальные `SELECT_PROFILE_SQL`/`UPDATE_PARAMS_SQL`), history/notify/advisory-хвосты writer'а покрыты фейком.
- Error propagation: все пути отказа → 503 «save failed» (fail-open чтения, отсутствующий ряд, конфликт), запись поверх чужих данных исключена.
- Regression risk: namespace-replace-семантика учтена read-modify-write; идемпотентный re-select без шума в history (`old_json != new_json` в writer'е).
- Производительность/безопасность: +1 SELECT на выбор (требуемый RMW); секретов нет; SQL-инъекций нет (параметризованные запросы writer'а); JS/фронт не менялся.

## Counterexamples checked (негативные/граничные)

- Пустой `style_id`/пробелы → strip → pop; выбор «пустышки» не пишет пустой пин. ✅
- PG-blip между read и write: guard `not root` → 503, деструктивной записи нет. ✅ (по коду)
- Отсутствующий chat_profiles-ряд → 503 (ChatParamsConflict), профиль создаёт lifecycle — задокументировано в evidence. ✅ (по коду)
- Повторный выбор того же стиля → UPDATE без дубля history. ✅ (по коду writer'а)
- Двойной pop / отсутствующий ключ при очистке → `pop(key, None)`, без исключения. ✅

## Blocking findings

Нет.

## Non-blocking debt (Low, фиксироваться вне хотфикса)

- **L-HOTFIX-1 (гонка RMW, унаследованный паттерн)**: read-modify-write в `cover_style_select` неатомарен (нет `expected_updated_at`) — конкурентный writer между чтением и записью потеряет свои override-правки. Тот же паттерн у принятого precedent'а `web/api/routes.py:967-980` (chat param reset) — хотфикс следует установленной практике; оптимистичный токен возможен как отдельное улучшение.
- **L-HOTFIX-2 (pre-existing, вне скоупа)**: `/cover/select` авторизует только глобальный `access` и пишет chat_params по client-supplied `chat_id` без per-chat проверки членства. Это §135-дизайн («выбор — access»), существует и pre-fix, хотфиксом не менялся; регистрирую как наблюдение для backlog'а.

## Unavailable checks

- Живой authenticated выбор стиля в мини-аппе (real Telegram init-data + real PG) локально невоспроизводим — отложен на prod-верификацию при деплое 2.58.43 (как заявлено в evidence; условие релиза за DevOps, прецедент rounds 10.28/10.29). HTTP-контракт верифицирован через реальный роутер (TestClient) + real chat_params — достаточный локальный прокси; UI (web/app.js) не менялся, browser-проверка не применима к diff'у.
- Нет: миграций, новых зависимостей, изменений auth/secrets — соответствующие deep-audit-категории N/A по скоупу.

## Вердикт

**Approved for release.** Оба дефекта корня (Д-1 `pg=`, Д-2 форма патча + RMW) исправлены корректно, закрыты 6 regression-тестами с независимым RED-on-pre-fix, полный pytest 10437/2 known без новых падений, F8 чист. Binding: апрув действителен только для состояния `0dc5679` + WTH `1647d903…`; изменение любого из 4 файлов скоупа или спеки инвалидирует гейт.
