# MOD-ACL-UX-01 — M2: канонический резолвер GLOBAL-дефолт → CHAT-override
<!-- branch: integ/unify-release | date: 2026-11-09 -->
<!-- authority: plans/owner_inputs/2026-11-09-mod-acl-ux-01.md §2.1–§2.3.1, §2.4, §4.2 -->

## 1. Что сделано

Один резолвер (`services/chat_params.py`) стал единственным источником истины
для правила «глобальное значение — наследуемый дефолт, чатовое — явный выбор».
Потребители, которые раньше повторяли приоритет сами, теперь вызывают его:

| Потребитель | Было | Стало |
|---|---|---|
| `services/feature_gates.py` | chat-gate → явный глобальный `flags.<f>_enabled` (тихий veto) → fallback → глобальный флаг | `chat_params.resolve_gate_capability`: chat-gate (INHERIT/ON/OFF) → глобальный слой; `COMPAT_OVERRIDE_KEYS` — документированный alias `permsoc` |
| `services/permsoc.py` (`master_enabled`) | собственная копия `gates.permsoc → overrides → hot` | `feature_gates.gates_enabled` → тот же резолвер |
| `services/mca_experience_jobs.py` (`learning_enabled_for_chat`) | `if not global: return False` (глобаль глушил чат) | `chat_params.resolve_param_capability` (строка 5 таблицы работает) |
| `services/mca_experience_jobs.py` (`review_enabled`) | глобальная настройка останавливала shared-job | только аварийные env-оси K1/K3 (`emergency_block`) |
| `services/worker_settings.py` | вторая копия `chat → global → default` с собственным кастом | `chat_params.read_override` / `read_global` |
| `web/api/gates.py` | плоский bool по каждой фиче | + аддитивный `states{}` (chat_state/desired/source/global_value/emergency_block/effective_runtime/ready/authorized/observed) |

Ключевые элементы `services/chat_params.py`:

* `INHERIT` / `ON` / `OFF` — три состояния чата; `chat_state()` их различает;
  отсутствие записи = `INHERIT`, явный `false` = `OFF` (разные состояния).
* `resolve_capability()` — чистое ядро без I/O;
  `resolve_param_capability()` (домен `overrides`),
  `resolve_gate_capability()` (домен `gates`),
  `resolve_module_capability()` (модуль реестра `module_registry`, без нового
  каталога).
* `CapabilityState` отдаёт раздельные оси: `desired`, `source`,
  `effective_runtime`, `emergency_block`, `ready`, `authorized`, `observed`.
  Один bool вместо них запрещён контрактом §2.2.
* Резолвер ничего не пишет: сохранённые `false` остаются `false`, INHERIT не
  материализуется в строку.

Формула: `desired = chat_override != INHERIT ? chat_override : global_default`;
`effective_runtime = desired AND NOT emergency_block AND ready is not False`.
Env kill-switch (`MCA_*`, K1–K4) — отдельная техническая ось, она перекрывает
`desired`, но не подменяет его значение.

## 2. Шесть строк таблицы §2.1 — где доказано

| GLOBAL | CHAT | effective | Тест |
|---|---|---|---|
| ON | INHERIT | ON | `test_six_case_table_global_module`, `..._per_chat_experience` |
| ON | ON | ON | то же |
| ON | OFF | OFF | то же |
| OFF | INHERIT | OFF | то же |
| **OFF** | **ON** | **ON** | то же (было сломано: `if not global: return False`) |
| OFF | OFF | OFF | то же |

Дополнительно (интеграция shared-worker, §2.3.1):
`tests/test_asap8_v6_d05_experience.py::test_u4_global_off_chat_on_still_learns` —
при GLOBAL OFF + chat ON тик **completed**, сигнал записан только в eligible-чат,
INHERIT-чат не тронут, stored override не переписан.

## 3. Before/after impact report

Скрипт: `scripts/mod_acl_effective_state_report.py` (read-only).

* `--fixture <json>` — детерминированный прогон без БД (тест
  `test_impact_report_is_deterministic_on_fixture`);
* `--database` — READ-ONLY по production PostgreSQL (только SELECT
  `bot_settings`/`chat_profiles`; `PgDatabase.init()` не вызывается, ни DDL, ни
  сида, ни миграций).

Фикстурный dry-run: `plans/features/mod-acl-ux-01/reports/m2-impact-fixture-dry-run.md`
(вход `m2-impact-fixture.json`).
Итог на фикстуре: capability 16, чатов 4, изменённых пар 3, чатов с изменением
поведения **2** (поштучно: `-300` → `gate:dream`, `-100` → `gate:dream`,
`module:experience`). Все изменения — только `OFF → ON` (ни один чат не
выключился).

**Production-прогон — отдельный read-only шаг DevOps:**

```bash
POSTGRES_DSN=... python -m scripts.mod_acl_effective_state_report --database \
  --out <отчёт>.md
```

Скрипт ничего не пишет в БД; при отсутствии пула завершается с кодом 1 и
сообщением, что read-only прогон невозможен.

## 4. Тесты (изменения существующих ожиданий)

Тесты, зелёные на старом коде, но утверждавшие противоречащее контракту
поведение, обновлены вместе с реализацией:

* `tests/test_asap8_f5_module_truth.py::test_m6_global_default_is_inherited_not_prohibitive`
  (было `test_m6_global_master_off_disables_all_chats`);
* `tests/test_asap8_v6_d05_experience.py::test_u4_global_off_chat_on_still_learns`
  (было `test_u4_global_master_off_silences_all_chats`);
* `tests/test_mca16_experience_block_e_round1039.py::test_settings_apply_without_restart`
  (review_enabled больше не зависит от продуктового флага);
* `tests/test_settings_worker_sync_round1018.py`: `test_global_flag_is_default_not_veto`
  и `test_global_flag_does_not_veto_cognition_active` (бывший kill-switch-veto).

Новый файл: `tests/test_mod_acl_ux_m2_resolver.py` (10 тестов) — таблица, три
состояния, worker-выбор, отсутствие записи в хранилище, env kill-switch,
alias `permsoc`, раздельные оси, детерминизм отчёта.

## 5. Что осталось / риски

* При GLOBAL OFF и отсутствии eligible-чатов тик shared-job не выходит до SQL,
  а делает ограниченный проход детектора без LLM (не более `batch_max` строк за
  тик, per-chat гейт проверяется первым). Это цена того, что GLOBAL OFF больше не
  останавливает воркер при наличии явного чат ON (§2.3.1).
* `flags.dream_enabled` больше не является «тихим запретом»: явный чат ON
  исполняется. Это ожидаемое изменение (см. отчёт: класс `gate:dream`, только
  OFF → ON), сохранённые значения не переписаны.
* Production-цифры before/after появятся после read-only прогона DevOps.
