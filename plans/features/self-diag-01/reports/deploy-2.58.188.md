# Deploy 2.58.188 — SELF-DIAG-01 D2 (доступ к диагностике)

Выкладка на **production** (192.255.209.205, `/var/www/admin_bot`).

## 1. Границы выкладки

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.188` = `c087253dd7afdbcfa0c5ee96927324dc349627b2` |
| Принятый кандидат | `02e9d301358872a108f8094b0d3742dc0de2e741` (база `77a63bc5`) |
| Предыдущий прод | `952b9ebd` @ 2.58.187, schema 47 |
| MUTABLE_WORKTREE_REQUIRED | **no** — неизменяемый checkout по SHA, `dirty_tracked=0` |
| Repo write scope | `config/settings.py`, `plans/docs/param-registry-round1025.meta.md`, 24 python-пина тестов |
| Δ DDL / Δ migration / Δ flag | **0 / 0 / 0**, схема остаётся v47 |

### Порт

`git rebase --onto 952b9ebd 77a63bc5 02e9d301` — 5 коммитов, **конфликтов нет**.

Ожидавшиеся конфликты в `services/tool_router.py` и `web/api/access.py` не возникли:
все пять изменённых срезом файлов (`handlers/checkup.py`, `services/access.py`,
`services/chat_keys.py`, `services/tool_router.py`, `web/api/access.py`) **байт-в-байт
совпадают** в `77a63bc5` и `952b9ebd` (blob-id равны: `6ab86732`, `d29119da`,
`2e70f6d3`, `670245e1`, `dc18b1e2`). Прод эти файлы после базы не трогал.

### Дельта `952b9ebd..c087253d`

9 файлов среза (содержимое пофайлово идентично `02e9d301`) + 26 файлов bump версии:

```
A services/diagnostic_policy.py      A services/output_projection.py
A services/telegram_role_check.py    A tests/test_diagnostic_policy.py
M handlers/checkup.py                M services/access.py
M services/chat_keys.py              M services/tool_router.py
M web/api/access.py
```

Полное сравнение деревьев по blob-id: изменились ровно 9 путей из 9394/9398,
остальные **9389 путей байт-в-байт равны** `952b9ebd` — включая контур инспектора
(`services/turn_payload_events.py`, `turn_trace.py`, `turn_types.py`,
`social_turn_frame.py`), контур памяти (`direct_chat_service.py`,
`mca_retrieval_context.py`, `summary_memory.py`, `memory_*.py`) и
security-модули (`hot_config.py`, `key_history.py`). `services/database.py`
не менялся → `user_version` v47 (`_SCHEMA_VERSION_SEMANTIC_SCHEDULE = 47`).

## 2. Предрелизная проверка (точно на `c087253d`)

| Набор | Результат |
|---|---|
| `tests/test_diagnostic_policy.py` | **71 passed** |
| целевой набор (access/roles/checkup/tool_router/chat_keys/api/ADR-1019) | **519 passed, 1 failed** |
| tool-набор (16 файлов) | **392 passed, 2 failed** |
| log-набор (6 файлов) | **137 passed, 1 failed** |
| version-пины (24 файла) | **811 passed, 1 failed** |
| `test_evol_evidence_routing.py` (ADR-1019) | **116 passed** |

**Классификация падений — все предсуществующие, воспроизведены на `952b9ebd`
в отдельном worktree с идентичным текстом ошибки:**

| Тест | Причина | На `952b9ebd` |
|---|---|---|
| `test_chat_keys.py::test_parallel_generate_usage_attributed_per_chat` | `TypeError: fake_post() got an unexpected keyword argument 'sent'` — устаревший стаб в тесте, `services/llm_client.py` дельтой не менялся | падает так же |
| `test_hotfix_round1025_logging.py::...test_log_has_text_provider_model_timeout_attempts` | тот же `sent` в `_FallbackStub._post_fallback` | падает так же |
| `test_addtr_tools_minifix.py::test_l1_seam_announce_then_execute_once` | посторонний L1-шов, дельты не касается | падает так же |
| `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff` | guard сравнивает `git diff pre-round1026-a1` — историческая релизная привязка | падает так же |
| `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` | то же, другая базовая метка | падает так же |

Новых падений дельта не даёт: 0.

## 3. Выкладка

- `git fetch origin release/2.58.188` → `git checkout -f -B release/2.58.188 c087253d` →
  `dirty_tracked=0`, `APP_VERSION=2.58.188`.
- Снапшот SQLite: `/tmp/predeploy-258188.db`, 2 267 840 512 B,
  read-back `user_version=47`, `PRAGMA quick_check=ok`, 48 колонок `smart_messages`.
- `systemctl restart admin_bot` в 09:21:08Z; healthz 200 на первой же попытке.

## 4. Пост-деплой

| Проверка | Факт |
|---|---|
| `/healthz` локально | `{"status":"ok","version":"2.58.188"}` |
| `/healthz` публично | 200, `2.58.188` |
| Unit | `active`, **NRestarts=0**, `ExecMainStatus=0`, MainPID 3982405 |
| Схема | `user_version=47` (не изменилась) |
| Журнал с рестарта | 193 строки: `CRITICAL` **0**, `Traceback` **0**, ` ERROR ` **0**, `database is locked` **0**, WARNING 1 |
| Единственный WARNING | `SmartModule: embedding generation not serviceable | index=smart_archive | status=superseded — FTS-only (A06)` — предсуществующий: 6 таких же строк в журнале за 11.11 до рестарта |
| Секрето-подобные строки в журнале | bot-token **0**, `Bearer` **0**, DSN **0** |
| ADR-1019 guard на выложенном дереве | `test_scenario19_background_services_have_no_web_imports` — **1 passed** |
| Новые модули против поискового контура | `diagnostic_policy`, `output_projection`, `telegram_role_check`: forbidden `[]`, network `[]` |
| Диск | 35 048 MB свободно |

## 5. Политика на реальном боте (read-only, 0 отправленных сообщений)

Бот `PERMsoc_bot` (8802473181). Метод: Bot API `getChatMember` + вызовы выложенных
`services.diagnostic_policy` / `telegram_role_check`.

**Три инструмента среза** (`destination=tool` и `tool_result`):

| Инструмент | Класс данных | Решение | reason_code | verification |
|---|---|---|---|---|
| `get_bot_health` | PUBLIC_TECH | allow | `allowed_public_class_default` | `not_required` |
| `read_source_code` | PUBLIC_TECH | allow | `allowed_public_class_default` | `not_required` |
| `inspect_runtime` | CHAT_SCOPED | allow | `allowed_public_class_default` | `not_required` |

Это соответствует ТЗ-строке SD1-AC-10 («публичный пользователь видит подробную
техническую информацию, кроме credential values и чужих chat contents»):
класс PUBLIC_TECH/CHAT_SCOPED заводски разрешён и участнику. Роли различаются
только в protected-классах — там решение идёт через живой Telegram.

**Protected-класс `prompts`, живой Telegram** (два реальных чата, реальные аккаунты):

| Чат | Аккаунт | getChatMember | Решение | reason_code |
|---|---|---|---|---|
| -1004482340693 | 5885953495 | administrator | **allow** | `allowed_chat_admin_default` |
| -1004482340693 | 138811255 | administrator | **allow** | `allowed_chat_admin_default` |
| -1004482340693 | 350803143 | left | **deny** | `denied_prompt_content_member` |
| -1004482340693 | 479167456 | TelegramBadRequest | **unverified** | `denied_auth_unverified` |
| -1002661910336 | 5885953495 | member | **deny** | `denied_prompt_content_member` |
| -1002661910336 | 138811255 | member | **deny** | `denied_prompt_content_member` |
| -1002661910336 | 350803143 | member | **deny** | `denied_prompt_content_member` |
| -1002661910336 | 479167456 | TelegramBadRequest | **unverified** | `denied_auth_unverified` |

**Секреты.** Набор `known_secret_values` собран без БД и с БД одинаково:
**17 значений**, `complete=true`, `reason=secret_sources_complete`, `missing=[]`;
среди них 17 env-имён (`API_TOKEN`, `POSTGRES_DSN`, `LLM_API_KEY`, `EXA_API_KEY`,
`GROQ_API_KEY`, `SENTRY_DSN`, `LOGTAIL_SOURCE_TOKEN`, …). Проверка санитайзера на
6 реальных значениях: `still_in_output=false` во всех, `sanitizer_leaks=0`,
`report_status=partially_redacted`. Реальный путь `ToolRouter._diagnostic_output`
для всех трёх инструментов: подсаженное значение заменено на
`«скрыто:LOGTAIL_SOURCE_TOKEN»`, `contains_plant=false`.

## 6. Откат

`git checkout -f -B release/2.58.187 952b9ebd` + `systemctl restart admin_bot`.
`952b9ebd` присутствует на сервере (`git cat-file -t` = commit, `APP_VERSION=2.58.187`).
Схема и данные не менялись (v47, DDL=0), поэтому откат кода безопасен без работы с БД.
Точка восстановления данных: `/tmp/predeploy-258188.db` (v47, `quick_check ok`).

## 7. Что осталось живым

- **SD1-D2-03 / SD1-D2-03b** — снято этой пробой (`evidence/d2/sd1_d2_03.json`),
  кроме статуса `creator` (не наблюдался: ни один из опрошенных аккаунтов не создатель
  этих двух чатов) и ветки «бот не имеет прав в чате» (getChatMember отвечал даже там,
  где бот только `member`; эквивалентный fail-safe `telegram_api_error → unverified`
  наблюдался на 479167456).
- **SD1-AMX-08** — механизм перепроверки перед публикацией выполняется
  (`tool_result`, `fresh_telegram=True`, решение пересчитывается); фактический отзыв
  админства на середине вызова не воспроизводился: это изменение прав в чужом чате.
- **SD1-AC-10 / SD1-AC-11 / SD1-AC-14** — наблюдаемы и наблюдались на уровне политики
  и санитайзера (см. §5). Полный прогон «живой ход бота → реальный ответ в Telegram»
  не выполнялся: тестовых сообщений в рабочие чаты не отправлялось.

## 8. Гейт требований

`requirements_gate.py check --stage release --slice D2 --candidate c087253d
--deployed-commit c087253d` → **exit 1**, 104 ошибки, из них по существу:

1. `candidate mismatch` — карта привязана к `02e9d301`, а выложенный кандидат `c087253d`;
   отсюда каскад «no evidence bound to reviewed candidate» на 40+ строках D2.
2. `required dependency D1 is not evidenced VERIFIED` — граф среза D2 объявляет
   зависимость от D1, строки D1 в карте остаются PENDING.
3. `SD1-D2-03: mandatory not ['VERIFIED'] (got READY_FOR_LIVE)` — статус в карте
   не обновлён под снятое живое доказательство.

Это **книжная работа PM/Orchestrator** (единственный писатель карты): перепривязка
candidate/evidence на `c087253d` и решение по зависимости D1. Код и прод при этом
исправны — гейт отражает состояние карты, а не дефект выкладки.
