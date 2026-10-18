# PERSIST-FIX (lane, P0 save/init §2) — отчёт

Дата: 2026-10-18 (UTC+ местное). Прод не трогался: изменения только в рабочей
копии (коммита нет — на независимое ревью). Источник задания:
`plans/features/p0-save-init-ux/source-p0-hotfix-2026-10-18.md` §2 +
`persistence-audit.md` (§3.1–3.5, B4/B5, §8.5–8.6).

## 0. Кандидат и изменённые файлы (sha12 = git blob текущей копии)

HEAD репозитория двигался другими lane во время работы (04c27b24 → 8c88bbda);
мои изменения — относительно рабочей копии, чужие uncommitted-файлы не тронуты.

| Файл | sha12 | Что |
|---|---|---|
| `web/api/speech.py` | a27a7b868eff | pg в 4 прямых записях, человеческие статусы, `_as_doc`, маршрут примеров |
| `services/config_cache.py` | d3729caa3efc | `set` = PG-first + явная ошибка без пула |
| `services/style_policy.py` | 9e7ec77e880b | фатальная валидация (unknown kind), conflict≠save_error |
| `services/prompt_factory.py` | 4ffc4c38ad35 | `reset_chat_override`: чтение с pg (RMW) |
| `services/mca_humor_feedback.py` | 8acbc226a88c | `set_paused`/`reset_learning` c pg, честный reset |
| `tests/test_p0_persistfix_speech_chat_scope.py` (новый) | eb96e665357e | 12 интеграционных тестов на реальном стеке |
| `tests/test_soul1_w6_speech_ui.py` | 7feee17d4955 | фикстура `api_env`: РЕАЛЬНЫЙ chat_params+пул |
| `tests/test_config_cache.py` | 7033127e00dd | честная семантика `set` (B4/B5) |
| `tests/test_soul1_w4_humor_feedback.py` | d449b64ff317 | owner-controls на реальном пути записи |
| `tests/test_asap42_step3_style_integration.py` | bbab0c68a913 | +bot_settings в схеме shim |
| `tests/test_asap44_cover_final_closure.py` | f6218188f51a | prompt-limit: реальная запись (не in-memory) |
| `tests/test_extra_cover_styles_api.py` | 805e50af73f3 | двойник пула с журналом записи |
| `tests/test_asap8_v6_wa1_config_cache.py` | f0edf4ec1fb1 | D08-write на пуле (не тихий in-memory) |
| `tests/test_hotfix4_cover_nav_shell_round1025.py` | 26034fdfb5ef | round-trip save на PG-backed кэше |

## 1. Прокидка `pg` во все 10 chat-записей (§3.1–3.4 аудита)

- `web/api/speech.py` ×4: `_write_document` (humor craft / examples policy),
  `_write_core_meta`, `_write_expression`, `post_expression_reset_chat`.
- `services/style_policy.py` ×2: `save_policy_document` и `reset_chat_policy`
  вызываются с `pg=_doc_pg(cache)` из `post_style` / `post_style_reset_chat`
  (функции уже принимали pg — его не передавали).
- `services/prompt_factory.py` ×2: `write_speech_value` (chat) и
  `reset_chat_override` вызываются с pg; в `reset_chat_override` чтение RMW
  тоже идёт через pg-путь.
- `services/mca_humor_feedback.py` ×2: `set_paused`/`reset_learning` получили
  `pg=` и читают/пишут chat-слой через него.
- Честная ветка «пула реально нет» сохранена: `set_chat_params` по-прежнему
  поднимает `ChatLorePgUnavailable`, API отдаёт 503 с человеческим текстом
  (не 200 и не 409-код).

## 2. ConfigCache.set — правдивое сохранение (B4/B5)

`services/config_cache.py::set`: порядок «PG → память» (как в `set_many`);
нет пула → `ConfigCacheUnavailableError` (память не меняется). Раньше:
silent in-memory при PG down (B4) и «память уже изменена» при сбое PG-записи
(B5). Прод-поведение: все web-вызовы и так гейтят `pg_available`; падение
записи теперь видно как явная ошибка (speech → 503 человеческое).

## 3. Core chat-scope — 3 дефекта, 3 отдельных теста

- текст full/compact → 200 + read-after-write из `chat_profiles.chat_params`;
- `/core/meta` → 200 `ok:true` только при реальной записи (иначе 503);
- `reset(mode=chat)` → 200, без 500; повторный — честный `no_chat_override`;
- `post_block_rollback` для chat-scope тоже обёрнут (был незащищённый 500-путь).

## 4. Прочие поражённые пути

- humor craft (chat) → 200 + документ в БД; examples policy (chat) → 200;
- learning pause/resume/reset → 200 + `humor.feedback` в БД; сбой записи
  `reset_learning` больше не глотается (реальная причина, 503/409 + человеку);
- «Сбросить в inherited» ×2: style → реальный `ok:true` при наличии override
  (не ложное «переопределения не было»), ошибка → 503; expression → 200;
- find: `POST /speech/examples/{seed,policy,why}` были в тени маршрута
  `{sample_id}` (422 int_parsing) — исправлено конвертером `{sample_id:int}`
  (одна строка; иначе 10-я запись недостижима из HTTP).

## 5. Тихая потеря style-правил (unknown kind)

`validate_document` не подавлен; в `save_policy_document` добавлен
`fatal_document_issues` (unknown kind / не-объект / не-список) → `applied:false
reason=document_invalid blocking_issues=[...]` → POST /speech/style → 409 с
человеческим текстом и списком проблем; документ не записан.

## 6. Латентный JSON-string C1

`_as_doc` (по образцу `style_policy._as_document`) применён в
`_expression_document`, `_core_payload`, `_write_expression`, `_write_core_meta`,
`_write_document`.

## 7. Тесты

RED: `evidence/persist-fix/red-2026-10-18-pytest.txt` — 16 failed / 40 passed
(точные прод-ошибки: 503 «запись недоступна», 200 `ok:false`, 409
`write_error`/`save_error`, 503 «локальная запись недоступна», 422-тень,
`assert 9000 == 8000` на B5).
GREEN (финал): `green-final-pytest.txt` — 145 passed (5 файлов: P0-интеграция,
W6, config_cache, W4 humor feedback, style policy).
Sweep 130 файлов-потребителей на финальном коде: `sweep-130-final.txt` —
2985 passed, 1 failed (только чужой `mca12 js_ui_suite`: на HEAD-worktree
зелёный, падает из-за несохранённой правки `web/app.js` другого лейна).
Полный pytest (near-final кандидат, до последних трёх микро-правок):
`full-suite-post-fix.txt` — **14235 passed / 9 failed**; все 9 — чужие/
pre-existing (атрибуция `known-failures-attribution.txt` + HEAD-worktree:
t5150 v35→36 ×5, asap7_direct_settings v35 ×2, mca01 single-writer ×1,
mca12 js_ui_suite ×1 — чужая uncommitted правка app.js). После финальных
микро-правок перепрогнаны те же файлы — тот же список 9 (73 passed).

Класс дефекта теперь ловят:
- `tests/test_p0_persistfix_speech_chat_scope.py` — реальный HTTP-стек +
  реальные `chat_params`/`ConfigCache` поверх temp-SQLite: любая запись без pg
  падает так же, как в проде;
- `tests/test_soul1_w6_speech_ui.py` — фикстура больше НЕ подменяет
  `chat_params.set_chat_params` (аудит §4: «подменяли сам виновный вызов»);
- `tests/test_config_cache.py` — `test_set_without_pool_raises_and_keeps_memory`,
  `test_set_pg_write_failure_leaves_memory_unchanged`;
- `tests/test_soul1_w4_humor_feedback.py` — owner-controls на реальном пути.

## 8. Остатки/риски/incidental

- `set_many` при отсутствии пула по-прежнему пишет только в память (silent) —
  вне мандата брифа; в web-путях гейтится `pg_available` (routes.py:1161);
  кандидат на следующий P0-пункт.
- `prompt_factory._write_chat_speech_value` пишет провенанс ДО значения
  (аудит §8.6) — не менял (низкая важность, отдельный пункт).
- pre-existing failures, не связанные с лейном: `t5150 startup-migrations`
  (5 тестов, версии DDL 35→36 — чужая зона; падают и на HEAD-worktree) и
  `test_mca12_stories js_ui_suite` (строка статуса чата в web/app.js — чужая
  uncommitted-правка; на HEAD-worktree зелёный).
- Живой прод-прогон не делался (прод запрещён брифом).
