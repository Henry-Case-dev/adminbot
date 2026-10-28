# P0 admin-toggle-save — независимое ревью (LEAF: REVIEW-ADMIN-TOGGLE-SAVE), 28.10.2026

## Вердикт: **Approved**

Кандидат: `a602aa61` (ветка `task/admin-toggle-save`), база `9261565d` (deployed 2.58.139).
Worktree ревьюера: `C:\Code\Python\adminbot-wt-tgl-rev` (detached, чистый git status).
База для RED-сравнения: `C:\Code\Python\adminbot-wt-tgl-base` (detached `9261565d`).
Метод: воспроизведение, не доверие. Прод-сервер/SSH/Telegram не использовались.

## 1. Root cause — ПОДТВЕРЖДЁН (независимо)

- Код-цепочка: chat-путь `post_config` → `set_chat_params` со строгим optimistic-токеном
  (`UPDATE ... WHERE chat_id=$1 AND updated_at=$3::timestamptz`, chat_params.py:84-86 базы) →
  0 строк при устаревшем токене → `ChatParamsConflict` → 409 (routes.py). Подтверждено чтением базы.
- RED на чистой базе `9261565d` (тест-файл кандидата, скопированный на базу):
  `test_stale_token_toggle_still_applies_and_preserves_concurrent_write` FAILED,
  `test_missing_group_profile_first_write_ensures_and_saves` FAILED,
  `test_smart_cache_get_follows_hot_flag` FAILED (3 failed / 6 passed).
  На кандидате те же 9 тестов: 9 passed. Root cause → fix подтверждён экспериментом.
- UI-симптом консистентен: `web/app.js:10447-10448` — формат тоста
  «Сохранено N из M; не сохранено: ...» == прод-скриншоту владельца.
- `set_gates_opt_in` на базе сдвигал `updated_at` без NOTIFY — подтверждено дифом; NOTIFY-канон
  `set_chat_params` идентичен (`NOTIFY_SQL`, payload=str(chat_id)); слушатель канала
  `chat_params_updated` реально подключён в `bot.py:1276-1285,1356` (отдельное LISTEN-соединение,
  инвалидация ChatParamsCache, fail-open TTL-фолбэк).

## 2. Корректность фикса — VERIFIED (чтение кода + тесты)

`web/api/routes.py` `_write_chat_overrides_with_retry`:
- Ровно ОДИН ограниченный ретрай (нет цикла; повторная запись с `expected=None` не может снова
  поймать stale-конфликт — безусловный UPDATE). Структурный 409 сохранён: внешний catch в
  `post_config` остался (напр. ensure профиля не удался → 409 наружу).
- Отсутствующий профиль группы: `current_updated_at is None` → `ensure_scope_profile(dm=False)`
  (тот же ленивый ensure, что DM F-14) → запись. RED→GREEN подтверждён тестом.
- Stale-токен: перечит свежего root НАПРЯМУЮ из PG — `get_all_chat_params(chat_id, pg=cache.pg)`
  при явном pg минует `_chat_params_cache` (подтверждено кодом chat_params.py, D-2) → merge патча
  поверх свежих чужих значений. Чужие ключи не теряются; LWW только на пересекающихся ключах —
  trade-off задокументирован в fix.md, для админ-UI владельца приемлем.
- Права/типизация ДО записи: в `post_config` — access_for/can_access_chat, per-key effective_matrix
  + can_edit_param (матрица из perm_overrides/db_overrides, НЕ value_overrides), _coerce_value/select
  — всё до вызова хелпера; ретрай переписывает те же уже валидированные ключи патча.
- D-409-1 идемпотентный short-circuit первой попытки сохранён (проходит через хелпер без изменений).

`services/chat_params.py` `set_gates_opt_in`: добавлен NOTIFY тем же каналом/payload, что весь
write-path; fail-open try/except (не-PG двойники — skip).

`services/smart_cache.py` `get()`: рубильник/TTL переведены на hot (`flags.smart_cache_enabled`,
`limits.smart_cache_ttl_seconds`, settings-фолбэк) — паттерн байт-в-байт как `set()`/`_active()`/
`get_dedup()` (T-619). R51-3 env-аварийный рубильник сохранён (settings остаётся дефолтом hot).
Тест двунаправленный: settings OFF + hot ON → отдаёт; settings ON + hot OFF → None (и `_read`
не вызывается). Семантика dedup (`chat_dedup_enabled`) не тронута.

## 3. Аудит-матрица — ВОСПРОИЗВЕДЕНА НЕЗАВИСИМО (артефакты Builder'а утеряны)

Артефакты `flags_audit.json`/`flags_consumers.json` НЕ найдены ни в OpenCodeScratch, ни в temp,
ни в worktree Builder'а (каталог tgl-ui-probe пуст). Заявление 106/106 поэтому не принималось на
веру — ревьюер воспроизвёл аудит сам на кандидате (реальный ConfigCache + реальный chat_params
поверх sqlite-шима, реальный TMA-флоу):

- Популяция: 107 bool-спеков категории flags по `spec.pg_key` (106 WORKS + 1 BROKEN-fixed
  `flags.smart_cache_enabled` — сходится с матрицей fix.md).
- На КАЖДЫЙ из 107: global POST → 200, hot отражает True, глобальный readback True;
  chat POST (свежий токен из GET) → 200 через реальный retry-путь, override=False применён в
  chat_profiles. **Результат: 107/107 PASS, 0 отказов** (мои артефакты:
  `%TEMP%\opencode\rev_flags_audit.json`, `rev_flags_consumers.json`).
- Потребители: все 107 имеют ссылки (литерал pg_key или settings_field) в services/handlers/
  filters/SmartModule/bot.py. Спот-чек 5 случайных: belief_decay (dream_worker.py:1322 hot.get),
  olya_caption_mention (filters/olya_video.py:92 hot.get), graph_user_quota
  (summary_memory.py:3504 hot.get), vision_media_gif (mca_vision.py:195→202 media-гейт),
  ytdlp_for_youtube (settings-синхро-цепочка: mca_process_registry.py:753 settings_ref +
  config/settings.py:2951) — рантайм-потребители реальны.

## 4. Тесты и регрессии (все прогоны ревьюера, локальный харнесс)

- Новый файл: кандидат 9 passed (11.6s); база 3 failed/6 passed (ровно root-cause блок) — RED→GREEN.
- Фокус-регрессии (шире списка fix.md, 25 файлов): **571 passed, 4 failed**; все 4 падения
  воспроизведены 1-в-1 на чистой базе `9261565d` (mca10a ×2 Settings 465 vs 466 — след fcpost;
  soul1_registry ×2 пины персоны) — предсуществующие линии релиза, к кандидату отношения не имеют.
- fcpost W1+W2 + factcheck/speech-смежные (10 файлов): **204 passed, 2 failed**;
  `TestAggregatorFailureTaxonomy::test_timeout_is_not_provider_unavailable` и
  `test_api_error_is_provider_error` падают ИДЕНТИЧНО на чистой базе — DDG-провайдер реально
  ходит в сеть (среда без сети → empty_results вместо мок-причины). `search_aggregator.py`
  кандидатом не тронут. Предсуществующая средозависимая хрупкость, не регрессия.
- `tools/gen_param_registry_round1025.py --check` → CHECK OK: реестр 586 == REGISTRY (rc=0).
- Каталог не менялся (диф: 8 файлов, param_catalog отсутствует). Пины F11 переутверждены синхронно
  в каноне и дубле (одинаковый новый SHA); routes-инвентарь не менялся (Δroutes=0 подтверждён дифом).
- Worktree кандидата после прогонов: git status чистый.

## 5. Леджер приёмки (lane-скоуп)

| Пункт | Статус | Доказательство |
|---|---|---|
| Root cause воспроизведён на базе | VERIFIED | RED-прогон на 9261565d (3 failed) |
| Фикс write-path (1 ретрай, merge, ensure, права до записи, 409 структурный) | VERIFIED | код + 9/9 GREEN + RED→GREEN |
| Read-side get()↔hot (оба направления, R51-3 сохранён) | VERIFIED | код + тест (база RED, кандидат GREEN) |
| NOTIFY set_gates_opt_in + слушатель | VERIFIED | диф + bot.py:1276/1356 |
| Аудит-матрица 106/106 (+1 fixed) | VERIFIED | независимое воспроизведение 107/107 (артефакт Builder'а утерян) |
| Пины F11 / реестр / каталог | VERIFIED | --check OK, Δroutes=0 |
| W1 fcpost / speech / factcheck смежные | VERIFIED | 204 passed; 2 падения идентичны базе (средовые) |
| Живой владелец-чек на устройстве | N/A_WITH_REASON | стоячее правило PET_PROJECT: добровольное наблюдение, инженерная приёмка на реальном UI-коде Builder'а (Playwright PROBE-2/4/5) |

## 6. Неблокирующие наблюдения (backlog, не активный скоуп)

1. Ретрай-лег использует perm-матрицу, прочитанную ДО первой попытки: микросекундное окно
   «право отозвали между чтением и merge-записью». Окно существует и на happy-path (прежний код),
   ретрай расширяет его на длительность ретрая. Для 1-2 чатов владельца — незначимо.
2. Предсуществующие падения на линии релиза (mca10a ×2, soul1_registry ×2, fcpost-DDG ×2) —
   не этого кандидата; PM может собрать в отдельный tidying-тикет.
3. Артефакты аудита Builder'а (`flags_audit.json`) утеряны — следствие перехода scratch между
   worktree; мои артефакты сохранены в %TEMP%\opencode\.

## Binding

- Кандидат: `a602aa61` = `9261565d` + диф 8 файлов (3 продукт-файла, 4 теста, evidence).
- Среда: локальный pytest/TestClient + sqlite-шим (шаблон persistfix-харнесса), Python 3.12 venv.
- Прод не задеплоен (кандидат — следующий релиз); по стоячему правилу PET_PROJECT выкат
  готовой проверенной функции — штатным следующим релизом.