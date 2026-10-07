# `mca-release` — намеренно-неактивные оси: артефакты (T-5224, 07.10.2026)

**Лейн:** B2-mcarelease-laneA (Builder). Задача: **подтверждение артефактами, не изменение** (spec mca-release §1/D3, SC-R2c). Источник факта — живой прод 2.58.66 (`e16be7e`), read-only, 0 переключений. R17: секреты/env-значения не печатаются, chat-ID маскированы.

---

## 1. Игровой stub mca-10c §14.12 (`:718–728`, A36 `:917`) — не зарегистрирован и не активен

### 1.1 Пробный вызов на проде → `not_implemented` (артефакт)

Вызов выполнен на проде (`/var/www/admin_bot`, системный python3; модуль `services/mca_game_stub.py` импортирует только stdlib — 0 сетевых запросов, 0 БД, 0 scheduler, 0 событий по дизайну модуля и тесту `tests/test_mca10c_game_stub_round1042.py::test_stub_returns_not_implemented_without_side_effects`):

```
$ python3 -c "import asyncio; from services.mca_game_stub import GameStub; \
  o=asyncio.run(GameStub().run('release-probe-t5224')); \
  print('STUB_OUTCOME:', o.status, '|', o.reason, '|', o.stub_version, '|', o.detail)"
STUB_OUTCOME: not_implemented | game_stub_inactive | mca10c-v1 | game action not implemented: release-probe-t5224
```

- `status = not_implemented` = `OUTCOME_NOT_IMPLEMENTED` (`services/mca_game_stub.py:37`);
- `reason = game_stub_inactive` (локальный код причины, в канон `mca_events.REASON_CODES` не добавляется — reason_code Δ=0);
- случайного результата нет, side effects нет (0 draw, 0 записей в `mca_random_draws` — подтверждено составом таблицы: 28 строк, все `sleep_after_consolidation`, новых от probe нет).

### 1.2 Отсутствие регистрации (вне SmartModule, без tools/handlers/UI)

```
$ grep -rl 'mca_game_stub' --include='*.py' services/ web/ bot*.py main*.py
(пусто — только tests/, см. полный grep ниже)

$ grep -rln 'mca_game_stub' --include='*.py' .
./tests/test_mca10c_game_stub_round1042.py
```

Единственная ссылка в коде прода — тест; в SmartModule/tools/handlers/UI/роутерах регистраций **0** (grep по `services/ web/` без учёта самого модуля — 0 строк). Файл на проде байт-в-байт с HEAD: SHA256 `2eb45ae9…c01d3` — совпадает с локальным HEAD `e16be7e`.

### 1.3 Вывод

Stub **не зарегистрирован и не активен**, вызов возвращает честный типизированный `not_implemented` без сетевых запросов и side effects — §20.2 строка 11 и §21 п.6 (`:1055`, «отдельно подтвердить неактивность игрового stub») выполнены. Активация — только будущей реализацией игр поверх DI-шва `RandomSourceService`; включение владельцем «по ходу» не предусматривается конструктивно (kill-switch не вводился — requirements-map §6 п.3).

---

## 2. Новые денежные ограничения — OFF (`:1026`; учёт расходов работает `:752`)

### 2.1 Состояние настроек лимитов из прод-runtime (артефакт)

**Env-слой (прод `.env`, имена без значений):**

```
$ grep -cE '^MCA_[A-Z_]+=' .env
MCA_ENV_KEYS=0
```

Ключей `MCA_*` в env прода **нет вообще** → `MCA_MONEY_LIMITS_ENABLED` = default **False** (`config/settings.py:1421–1422`), `MCA_MONEY_LIMIT_{DIRECT,AUTONOMOUS,MAINTENANCE}_USD` = None (не заданы, `:1423–1428`). Полный список имён env прода (значения скрыты) содержит только legacy-настройки (ALAN_*, FACTCHECK_*, LIMITS-предки, POSTGRES_*, API-ключи провайдеров — вне MCA-оси).

**PG-слой (`bot_settings`, 476 ключей):** скан по маскам `money`/`spend` — **0 ключей** (денежные ограничения — env-only ось, в БД не хранятся и не переопределяются).

### 2.2 Вывод

Effective состояние денежных ограничений = **OFF** — совпадает с санкционированным `:1026`. Это OFF-ось, не дефект: учёт расходов при отключённых лимитах работает (`:752` — существующий cost-учёт провайдеров активен, см. также строку 18 таблицы). Включение лимитов — только явная санкция владельца **вне этого раунда**; в гайдах/отчёте — честная пометка, не реклама (D3).

---

## 3. Квантовая честность — кросс-ссылка (D4, `:988`/`:1032`)

Статус ANU проверен **отдельно** от настройки (полная строка №12 в `effective_state_table.md`):

```
mca_random_state (SQLite, прод): scope='anu', key_fingerprint=None,
activation_batch_id=None, activated_at=None,
last_fallback_reason='provider_unconfigured'
DRAW| pseudorandom | python-random | provider_unconfigured | 28
[random_source] startup | {'status': 'blocked', 'reason': 'provider_unconfigured'}
```

- Настройка `memory.random_source="quantum"` (PG) — **выбран**;
- активация с реальным ключом — **не состоялась**: ключи `keys.random_quantum_*` в PG отсутствуют (env `RANDOM_QUANTUM_API_KEY` тоже не задан — в списке имён `.env` отсутствует);
- все 28 draws — pseudorandom fallback по явной политике `memory.random_fallback_to_pseudorandom=true`; функция случайности работает, формулировка «квантовый режим работает» **не используется**;
- несуществующие credentials не включались ✓.

Квант — **КРАСНАЯ строка** таблицы (расхождение с санкционированным «активирован с реальным ключом»), вынесена в отчёт лейна немедленно, переключения/настройка ключей этим раундом не выполнялись.

---

## 4. Источники и дисциплина

- Прод: `/healthz` = 2.58.66; git HEAD `e16be7e`; пин `routes.py` `8153b8bd…` цел.
- Чтение: HTTP + SSH single-login по AGENTS.md (без переборов/поллеров), SQLite/PG — read-only (`mode=ro` / SELECT), journalctl — только grep-чтение. Состояние прод-стейта не менялось: 0 переключений, 0 записей, 0 конфиг-правок (CA-REL-4).
- Смежные артефакты: `effective_state_table.md` (21/21 строк, T-5223); raw-выдержки — в этом файле, маскированы (R17).
