# R3b → откат канонов до 2.58.113 (REL-F1)

**Статус:** закрывает блокер **F1** релизного ревью 2.58.114
(`plans/features/_audit-2026-10-23/release-258114/review-rel.md` §6, §9).
**Дата:** 24.10.2026. **Код:** 2.58.114 (`bd1cdc3d`, каноны R3b).

## 1. Что было не так

`ROLLBACK_MIGRATIONS` хранил ровно одну пару `(новый канон, прежний канон)`
на ключ. Для R3b это давало:

* L1: `6c2ddc17c998` (8261 симв.) → `ab6817a18657` (канон R3, 7691) —
  и **стоп**: второй вызов `rollback_prompt_canons` был no-op, хотя канон
  прод-релиза 2.58.113 — `c987c03e3ee0` (6542). Полного возврата не было.
* L2: `83ff62bbee40` (3081) → `d1b210c156c8` (прод 2.58.113, 2827) — одна
  ступень, здесь цепочка уже заканчивалась корректно.
* Холодный `git revert` на `eb3abd63` (2.58.113) **не возвращает** промпты:
  его карта отката не знает новых байтов (`6c2ddc17`/`83ff62bb`), поэтому
  `migrate_prompt_canons`/`rollback_prompt_canons` версии 2.58.113 считают
  их «кастомом» (`WARNING ... кастом юзера — НЕ трогаем`) и ничего не пишут.

## 2. Что изменено

| Файл | Изменение |
|---|---|
| `services/prompt_migrations.py:370` | тип `ROLLBACK_MIGRATIONS: dict[str, list[tuple[str, str]]]` — у каждого ключа **упорядоченная цепочка ступеней** `(new → old)`; старые ключи = цепочка из одной ступени (поведение не изменилось) |
| `services/prompt_migrations.py:400` | L1: две ступени `(6c2ddc17 → ab6817a1)`, `(ab6817a1 → c987c03e)`; L2 (`:390`): `(83ff62bb → d1b210c1)` |
| `services/prompt_migrations.py:590` | `rollback_prompt_canons` снимает **одну** ступень за вызов (идемпотентно): ищет текущее значение среди `new` цепочки; на последнем `old` — no-op; неизвестные байты — `WARNING`, не трогает |
| `services/prompt_registry.py:2125` | `known_canon_hashes` читает все ступени цепочек (граница «канон vs кастом» не сузилась) |
| `tests/test_prompt_migrations.py:726` | новый dry-run тест на байты 2.58.113 (см. §3) |
| `tests/test_asap_speech_r3b_canon.py:122` | цепочка вместо «одной ступени» + 3-й вызов no-op |
| `tests/test_asap2_clar_contract.py`, `test_direct_l1_l1d_contract.py`, `test_cfg07_backstage_contract.py`, `test_factcheck_deep_context_round1023.py`, `test_hotfix4_cover_nav_shell_round1025.py`, `test_summary_l1_clusterizer.py`, `test_summary_l2_writer.py`, `test_unified_core_route_coverage.py` | формулировки «одна ступень» → первая ступень цепочки / полная цепочка; смысл пинов не ослаблен (первая ступень по-прежнему ведёт на непосредственный прежний канон) |

**Сколько шагов до 2.58.113:** L1 — **2** вызова `rollback_prompt_canons`,
L2 — **1** (второй общий вызов для L2 — no-op). Итого процедура = 3 вызова
функции, третий контрольный (должен вернуть `{}`).

Каноны-цели 2.58.113: L1 `c987c03e3ee0…748c` (6542 симв.),
L2 `d1b210c156c8…1b42` (2827 симв.) — подтверждено прод-снимком
`plans/features/asap2-direct-chat/evidence/prod-snapshot/report.md` §3.

## 3. Dry-run на копии прод-значений

In-memory копия PG (stored = фактические байты 2.58.114, реальные константы
`chat_prompts`), плюс владельческий кастом в соседнем ключе. Ничего в БД не
писала. Сырой лог: `evidence/r3b/raw/rollback-dryrun.json`,
тест-пруф: `tests/test_prompt_migrations.py::TestRound1023Migration::test_r3b_rollback_chain_restores_258113_bytes`.

| Шаг | Действие | report | L1 stored | L2 stored | кастом |
|---|---|---|---|---|---|
| 0 | исходно (прод 2.58.114) | — | `6c2ddc17c998` / 8261 | `83ff62bbee40` / 3081 | без изменений |
| 1 | `rollback_prompt_canons()` | L1+L2 `rolled_back` | `ab6817a18657` / 7691 | `d1b210c156c8` / 2827 | без изменений |
| 2 | `rollback_prompt_canons()` | только L1 `rolled_back` | `c987c03e3ee0` / 6542 | `d1b210c156c8` / 2827 | без изменений |
| 3 | `rollback_prompt_canons()` | `{}` (no-op) | `c987c03e3ee0` / 6542 | `d1b210c156c8` / 2827 | без изменений |
| 4 | `migrate_prompt_canons()` (повторный deploy) | L1+L2 `updated` | `6c2ddc17c998` / 8261 | `83ff62bbee40` / 3081 | без изменений |

Проверки dry-run: байты L1/L2 равны `PREV_*` 2.58.113 (не только статус),
3-й вызов — no-op, кастом не тронут, повторный deploy снова применяет R3b —
все `true` (`all_pass: true`).

## 4. Runbook: полный откат 2.58.114 → 2.58.113

Порядок **обязателен**: сначала откат канонов на живом 2.58.114 коде, затем
`git`-откат кода + рестарт. Готовит/выполняет @DevOps, ≤2 SSH-коннекта
(правила fail2ban в `AGENTS.md`).

### Шаг 1 — откат PG-канонов (код 2.58.114 остаётся задеплоен)

В рабочем каталоге unit `admin_bot` (там же, где `venv/`, тот же интерпретатор):

```bash
venv/bin/python - <<'PY'
import asyncio, hashlib
from services.config_cache import ConfigCache
from services.prompt_migrations import rollback_prompt_canons

KEYS = ("prompts.direct_l1_planner_system_prompt",
        "prompts.direct_chat_verbalizer_system_prompt")

async def main():
    cache = ConfigCache()
    await cache.init()
    try:
        for i in (1, 2, 3):
            print("call", i, await rollback_prompt_canons(cache))
        for k in KEYS:
            v = cache.get(k) or ""
            print(k, hashlib.sha256(v.encode()).hexdigest()[:12], len(v))
    finally:
        await cache.close()

asyncio.run(main())
PY
```

Ожидаемый вывод (sha12/длина — stored):

```
call 1 {'prompts.direct_chat_verbalizer_system_prompt': 'rolled_back', 'prompts.direct_l1_planner_system_prompt': 'rolled_back'}
call 2 {'prompts.direct_l1_planner_system_prompt': 'rolled_back'}
call 3 {}
prompts.direct_l1_planner_system_prompt c987c03e3ee0 6542
prompts.direct_chat_verbalizer_system_prompt d1b210c156c8 2827
```

Если `call 1/2` вернул `{}` или в логе `WARNING ... кастом юзера` — байты в
PG уже не равны ожидаемым: остановиться, снять дамп значений и вернуть
владельцу/дежурному (не перезаписывать вслепую).

### Шаг 2 — откат кода и рестарт

```bash
git checkout eb3abd63        # 2.58.113 + docs (release/2.58.113)
systemctl restart admin_bot  # плановый рестарт MANDATORY
```

### Шаг 3 — проверка после рестарта

1. `curl -s localhost:.../healthz` → `version = 2.58.113`.
2. Лог: `[prompt_migration] уже новый канон` для L1/L2 (значения 2.58.113
   совпадают с фабрикой этого кода); **не должно быть**
   `канон обновлён` для L1/L2 и не должно быть `кастом юзера` для них.
3. Stored совпадает с effective: L1 `c987c03e3ee0…748c` / 6542,
   L2 `d1b210c156c8…1b42` / 2827 (`factory == stored == effective` — факт
   для 2.58.113 зафиксирован в `prod-snapshot/report.md`).
4. Бэкап БД перед откатом обязателен (прецедент 2.58.113:
   `backups/pre_deploy_258113_*.db`, `integrity_check=ok`).

### Почему рестарт обязателен

До рестарта процесс 2.58.114 держит в памяти новые каноны; кроме того L2
удержан провенансом (`provenance_unavailable` → действует **фабрика** кода),
поэтому L2 приходит к 2.58.113 ровно на шаге 2, когда фабрика кода сама
становится `d1b210c156c8`. Промежуточное состояние «PG откатан, код новый»
не является полным откатом — не оставлять его на ночь/без рестарта.

## 5. Если холодный revert уже сделан

Симптом: на 2.58.113 в логе `WARNING [prompt_rollback] кастом юзера — НЕ
трогаем` для L1 и/или L2, stored = `6c2ddc17`/`83ff62bb`.

Восстановление (без перезаписи вслепую):

```bash
git worktree add /tmp/rel114 7ca3c684      # только код 2.58.114 для скрипта
cd /tmp/rel114
<APP_DIR>/venv/bin/python -                # тот же скрипт, что в §4 шаге 1
cd <APP_DIR> && git worktree remove /tmp/rel114
```

Скрипт не трогает работающий сервис (свой `ConfigCache`), пишет PG и
рассылает `NOTIFY`; значения в памяти старого процесса обновятся по
инвалидации, но полноценно применится после ближайшего рестарта.
Затем — проверка §4 шага 3.

**Чего нельзя делать:** запускать `migrate_prompt_canons` версии 2.58.114 на
откаченных байтах «чтобы проверить» — он вернёт новые каноны (это ожидаемое
поведение повторного deploy, см. dry-run шаг 4).

## 6. Прогоны (24.10.2026, worktree `release/2.58.114`)

| Набор | Результат |
|---|---|
| `tests/test_prompt_migrations.py` | **43 passed** |
| `tests/test_asap_speech_r3b_canon.py` | **7 passed** |
| `tests/test_asap_w1_semantics.py` | **21 passed** |
| смежные пины отката/лестниц (asap2 clar, l1d, cfg07, hotfix4, summary l1/l2, unified-core, factcheck 1023, asap21) | **464 passed** (13 файлов, 0 failed) |

## 7. Риски / границы

* Откат затрагивает только два ключа R3b; остальные цепочки — по одной
  ступени, их поведение и документированный смысл не менялись.
* Кастом владельца по-прежнему не перетирается: совпадение только по точным
  байтам известного канона, иначе `WARNING` и пропуск.
* Между шагом 1 и шагом 2 (секунды) L1 уже отдаёт канон 2.58.113, L2 — ещё
  фабрику 2.58.114 (провенанс); это осознанное окно, закрывается рестартом.
* Прод/SSH в этом лейне не трогались; dry-run — только in-memory + фикстуры
  реальных байтов.
