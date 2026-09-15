# Spec F2 — `direct-chat-budget-unlimited` (Безлимит по чату: sentinel вместо «0=запрет», per-chat резолв, устранение ложного sandbox)

> **Раунд:** 10.19, **итерация 2** (Step 2 @Architect, 15.09.2026). **Тип:** backend (`services/chat_usage.py`, `services/budget_limits.py` (новый), `services/llm_client.py`, `config/settings.py`, `services/param_catalog.py`). **Приоритет:** **P0** (бот уходит в sandbox-заглушки — прод-блокер общения).
> **ADR:** `adr-1019-2-budget-unlimited-sentinel.md` (**SUPERSEDE/AMEND F-15 раунда 10.3**) + **`../budget-settings-section/adr-1019-8-per-chat-limits-and-seed.md`** (мультичатовая модель, sentinel-таблица, сид настроек чатов).
> **Задачи:** T-1789…T-1798 + итерация 2: T-1854/T-1855. **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; каталог 436/90/406/411/88/19.
> **Источник:** `plans/current_task.md` UPD2 п.1 (строки 131-132) + чекап (строка 162) + **UPD3 п.2-3** (строки 184-207).
> **Конфликт файлов:** `services/chat_usage.py` (F3/F4 читают), `services/param_catalog.py` (F3/F4/F7), `config/settings.py` (F4/F7). **Порядок:** **F2 → F3 → F4**.
> **Статус реализации (Батч B, @Builder, 15.09.2026): ✅** `services/budget_limits.py` (sentinel-таблица семейств), per-chat резолв `chat_usage` (`resolve_setting_with_source`), `budget_snapshot`/`exceeded_metric`/`source` + fail-open, дефолты 100/500 000 и 60/300 000, тексты каталога (Δ=0), `llm_client` details из снимка. Тесты — `tests/test_budget_unlimited_round1019.py`. **Безлимит целевого чата (`-1002661910336`) — сид F3 T-1859** (в F2 не дублируется).
>
> **Ревью-фиксы Батча B (D-1…D-5, @Builder, 15.09.2026): ✅** фон-контур `worker_budget` — sentinel (`0=запрет`/`<0=безлимит`/`>0=cap`) + **per-chat** резолв (дефолты 60/300 000 действуют — D-1/D-2); fail-open `budget_snapshot` пробрасывает `forbidden`/`source` (D-4); `llm_client` — единый снимок без двойного PG-раундтрипа (D-5); ARCHITECTURE §40 + AMEND §22/§23 (D-3). См. `tasks.md` §11.
>
> **🔴 UPD3 (итерация 2) — корректировки F2 (обязательны):**
> 1. **Глобальный хардкод безлимита ЗАПРЕЩЁН** (UPD3 п.2). Безлимит — **только per-chat override**; глобальные дефолты остаются **консервативным предохранителем** (пересмотрены: 100/500 000 вместо 300/1,5M, см. §4.5).
> 2. **Sentinel-семантика — таблицей по семействам** (§3.1): бюджет `0=запрет`/`−1=безлимит` (канон F-7 подтверждён **осознанно**); retention `0=вечно`; контекст `0=не задано`/`−1=безлимит`. См. ADR-1019-8 §D2.
> 3. целевой чат `-1002661910336` получает безлимит **сидом** (`config/chat_settings_seed.json` + `services/chat_settings_seed.py`, ADR-1019-8 §D4) — id **не** в бизнес-логике.
> 4. **Изоляция памяти** (UPD3 п.2): аудит и инвариант строгой привязки памяти к `chat_id` — общий с F7 (ADR-1019-8 §D5-аудит), бюджетный контур не ослабляет scope.

## 1. Контекст и цель

Прод-лог (`2026-09-15T08:44:37`): `[direct] no key — sandbox answer | chat=-1002661910336 | reason=budget | details={'resolve_path': 'budget', 'day': '2026-09-15', 'used_calls': 25, 'limit_calls': 25, 'used_tokens': 699, 'limit_tokens': 100000, 'allow_global': True}`. Бот отвечает заглушкой «у чата нет своего ключа, а глобальный недоступен или исчерпан».

Факты:
- лимит **вызовов** (25) реально исчерпан; лимит **токенов** (100k) — даже близко нет (699);
- «Сводка» показывает лимиты **фонового** контура (35), поэтому владелец видит «не превышено» — это **другой контур** (обман восприятия, не баг расчёта);
- `chat_usage` читает лимиты **только из глобального слоя** `hot.get` — **per-chat override не работает вообще**, поэтому «выставить безлимит чату» сейчас негде;
- владелец требует безлимит для `-1002661910336` **без хардкода** и отдельный раздел настроек (F3).

**Цель:** ввести явный механизм «безлимит» (не через «0»), включить per-chat резолв лимитов, устранить неоднозначность `reason=budget`, пересмотреть прод-дефолты.

## 2. Текущее поведение (сверено с кодом HEAD `fd6acc7`)

- `services/chat_usage.py:53-60` — `_budget_limit_requests(default=25)` / `_budget_limit_tokens(default=100000)` — **только `hot.get`**, без `chat_id`.
- `services/chat_usage.py:100-113` — `budget_exceeded`: `if req_limit <= 0 or tok_limit <= 0: return True` (**любой ≤0 = запрет**); далее `used_calls >= req_limit` или `used_tokens + estimate > tok_limit`.
- `services/chat_usage.py:128-136` — `key_status` (used/limit calls/tokens), без признака безлимита.
- `services/llm_client.py:396-418` — ветка budget: re-read своего ключа → `NoApiKeyForChat("budget", details=…)`.
- `services/direct_chat_service.py:624-638` — sandbox `content.no_key_reply` при `NoApiKeyForChat`.
- `services/pg_db.py:181` — `chat_usage (chat_id, day, metric, used, PK(chat_id,day,metric))`.
- `config/settings.py:481-484` — `CHAT_GLOBAL_KEY_BUDGET_TOKENS=100000`, `CHAT_GLOBAL_KEY_BUDGET_REQUESTS=25`.
- `services/param_catalog.py:1232-1240` — REGISTRY `limits.chat_global_key_budget_*`, группа `limits_chat`, описания «0 — общий ключ чату запрещён».
- `services/chat_params.py:226-244` — `get_chat_param`/`_resolve_from_root` (эталон резолва, ADR-1018-7 D1); `:269+` — `set_chat_params` (запись `overrides`).
- **Смежный контур:** `services/worker_budget.py:210-217` (`_metric_limit`, per-chat 35) — изолирован от `chat_usage` (T-1795); **ревью-фиксы Батча B (D-1/D-2)** реализовали здесь sentinel (`0=запрет`/`<0=безлимит`) и per-chat резолв (UPD3 п.3: «Фоновый бюджет: −1 = Безлимит»), т.к. тексты каталога F2 уже обещают безлимит, а F3-тумблер пишет `−1`.

## 3. Требуемое поведение

### 3.1. Sentinel-таблица (итерация 2; источник истины — ADR-1019-8 §D2)

| Поле (`pg_key`) | `0` | `−1` / `< 0` | `> 0` | Глобальный дефолт | Семейство |
|---|---|---|---|---|---|
| `limits.chat_global_key_budget_requests` | **запрет** общего ключа чату (канон F-7/F-15 — **осознанно**) | **безлимит** | cap вызовов | **100** | бюджет ключа |
| `limits.chat_global_key_budget_tokens` | **запрет** | **безлимит** | cap токенов | **500 000** | бюджет ключа |
| `limits.worker_daily_llm_calls_per_chat` | **запрет** фонового расхода чата | **безлимит** | cap | **60** | бюджет фона |
| `limits.worker_daily_llm_tokens_per_chat` | **запрет** | **безлимит** | cap | **300 000** | бюджет фона |
| `limits.import_history_retention_days` | **вечно** (не бюджет! purge запрещён) | невалидно → fallback (WARNING) | хранить N дней | 180 | хранение (F7) |
| `limits.chat_global_context_max_tokens` / `…_thread_…` / `…_context_budget_…` | **не задано** → глобальный дефолт | **безлимит** (до ceiling) | cap | 5000/3000/16000 | контекст (F4) |

`0 = запрет` для бюджетов **сохранён** (обратная совместимость + требование канона). Для бюджетов `0` **не** переиспользуется под «безлимит». Хелперы: `budget_state()/is_unlimited()/is_forbidden()` — `services/budget_limits.py`.

### 3.2. Прочее

1. **Sentinel «безлимит»** для бюджетного лимита: любое **отрицательное** значение (`UNLIMITED = -1`) = метрика не ограничена. `0` **остаётся запретом** (подтверждено как осознанное решение).
2. **Per-chat резолв**: лимиты `chat_usage` читаются по чату (`chat_params.overrides[ключ]` → глобальный `hot.get` → env-дефолт) — тем самым настройка из UI доходит до воркера (снимает класс дефекта ADR-1018-7 для этого контура).
3. **Безлимит для `-1002661910336` — данными**, не кодом: запись per-chat override через `set_chat_params` / `POST /api/config` (+`X-Chat-Id`) **или сид настроек чатов** (`services/chat_settings_seed.py`, ADR-1019-8 §D4). Хардкода id в коде нет.
4. `reason=budget` **невозможен**, если ни одна метрика фактически не превышена: `budget_exceeded` возвращает метрику-причину; при `exceeded=True` причина обязана быть определена, иначе — ERROR-лог (внутренняя несогласованность) и fail-open в global.
5. `details` снапшот отражает режим: `unlimited: bool`, `forbidden: bool`, `exceeded_metric: 'calls'|'tokens'|None`, `source: 'chat'|'global'|'default'`.
6. Порядок резолва ключа **не меняется** (свой → `forbidden` → бюджет → BYOK-фоллбэк → global), sandbox — только при реальном отсутствии доступа (R16).
7. Изоляция контуров: правки `chat_usage` не меняют лимиты `worker_budget` (каждый контур резолвит **свои** ключи: `limits.chat_global_key_budget_*` vs `limits.worker_daily_*`); scope остаётся строго `chat:<id>` (без кросс-чат-утечки).
8. R17: `details`/логи — без токенов/ключей.

## 4. Технический дизайн

### 4.1. Новый модуль `services/budget_limits.py` (единый источник семантики)

```python
FORBIDDEN: int = 0          # 0 = запрет (сохраняем канон F-7/F-15)
UNLIMITED: int = -1         # любое < 0 = безлимит по метрике

def budget_state(limit) -> str:
    """'forbidden' (==0) | 'unlimited' (<0) | 'cap' (>0)."""
def is_unlimited(limit) -> bool: return int(limit) < 0
def is_forbidden(limit) -> bool: return int(limit) == 0
UNLIMITED_LABEL = "безлимит"          # для UI/логов
```
Никаких значений токенов/ключей; модуль — чистые хелперы (легко тестировать).

### 4.2. `services/chat_usage.py` — per-chat резолв + sentinel

- Сигнатуры (async, обратная совместимость через `chat_id=None`):
```python
async def _budget_limit_requests(chat_id: int | None = None,
                                default: int = 300) -> int: ...
async def _budget_limit_tokens(chat_id: int | None = None,
                               default: int = 1_500_000) -> int: ...
```
Резолв per ADR-1018-7: `resolve_setting_cached(KEY, chat_id=chat_id, default=hot.get(KEY, default))` (тонкая обёртка над `chat_params.get_chat_param`; `chat_id=None` → глобальный `hot.get`). Каст значения — как в `_resolve_from_root`.
- Ядро:
```python
def _exceeds(req_limit, tok_limit, used_calls, used_tokens, estimate):
    """('forbidden'|'unlimited'|'calls'|'tokens'|None)"""
    if budget_limits.is_forbidden(req_limit) or budget_limits.is_forbidden(tok_limit):
        return "forbidden"
    if not budget_limits.is_unlimited(req_limit) and used_calls >= req_limit:
        return "calls"
    if not budget_limits.is_unlimited(tok_limit) and used_tokens + estimate > tok_limit:
        return "tokens"
    return None

async def budget_snapshot(pg, chat_id: int, tokens_estimate: int = 0) -> dict:
    """Единый снимок: {exceeded, exceeded_metric, used_calls, limit_calls,
    used_tokens, limit_tokens, unlimited, day}. Fail-open (PG down) →
    exceeded=False, unlimited=False."""

async def budget_exceeded(pg, chat_id, tokens_estimate=0) -> bool:
    return (await budget_snapshot(pg, chat_id, tokens_estimate))["exceeded"]
```
- **Инвариант диагностируемости (T-1793):** в `budget_snapshot` при `exceeded=True` и `exceeded_metric is None` → `logger.error("[chat_usage] inconsistent budget state | chat=%s | …")` и `exceeded=False` (**fail-open**, не отправляем в sandbox без причины). Это исключает ложный `reason=budget`.
- `key_status` — аддитивно (R16):
```python
return {"calls":  {"used": …, "limit": …, "unlimited": bool, "source": "chat|global|default"},
        "tokens": {"used": …, "limit": …, "unlimited": bool, "source": "chat|global|default"}}
```

### 4.3. `services/llm_client.py` — details из снимка

В ветке budget (`:396-418`) вместо ручной сборки — `snapshot = await chat_usage.budget_snapshot(self._pg(), chat_id)`, `details = {"resolve_path": "budget", **snapshot}`. Добавить `exceeded_metric` и `unlimited`. Порядок резолва и BYOK-фоллбэк (`:400-403`) **не меняются**.

### 4.4. Точный путь записи безлимита (T-1792) — без хардкода

Единственный путь — данные чата (`chat_profiles.chat_params.overrides`):
```python
from services import chat_params
await chat_params.set_chat_params(chat_id, {"overrides": {
    "limits.chat_global_key_budget_requests": -1,
    "limits.chat_global_key_budget_tokens": -1,
}}, changed_by="admin")
```
- Операционно — через `POST /api/config` с `X-Chat-Id` (для `category=limits`, `per_chat=True`) **или** напрямую этим вызовом из F3-тумблера.
- Идемпотентно; откат — вернуть `25`/`100000` (или удалить override).
- **Прод-применение:** `-1002661910336` проходит через данные (UI/@DevOps), **id в коде отсутствует** (проверка @Reviewer, T-1798).

### 4.5. Прод-дефолты (пересмотр F-15 §6 и предыдущей редакции 300/1,5M) — консервативный предохранитель

**UPD3 п.5:** глобальные дефолты **не делаем безлимитными** — они предохранитель; безлимит — только per-chat. Ранее предложенные 300/1,5M пересмотрены в пользу умеренных значений.

| Ключ | Было (прод) | Рекомендуется | Обоснование |
|---|---|---|---|
| `limits.chat_global_key_budget_requests` | 25 | **100** | ≈1 вызов/10 мин при 16-часовом активном дне; живой одиночный диалог проходит с запасом; зацикливание всё ещё отсекается. Безлимит — только целевому чату (данными сида). |
| `limits.chat_global_key_budget_tokens` | 100 000 | **500 000** | 100 вызовов × ~5k токенов (расширенный контекст F4) = ~500k; токен-лимит перестаёт срабатывать раньше вызовного, но остаётся конечным. |
| `limits.worker_daily_llm_calls_per_chat` | 35 | **60** | несколько прогонов Сна/фона в день; предохранитель от зацикливания воркеров. |
| `limits.worker_daily_llm_tokens_per_chat` | 100 000 | **300 000** | согласовано с 60 вызовами × ~5k; глобальный фон-лимит (200/500k) **не меняется**. |

Те же значения — env-дефолты в `config/settings.py:481-493` **и** тексты каталога (`:1233-1240`, добавить: «−1 — безлимит»). **Важно:** env-дефолт сам по себе прод не меняет (PG-ключи засеяны `ON CONFLICT DO NOTHING`) → фактические значения пишет @DevOps/F3/сид (см. §7, ADR-1019-8 §D4/D7).
> **Целевой чат `-1002661910336`:** бюджеты `−1` — **данными** (сид/UI), не через смену глобального дефолта. Безлимит как «новый стандарт» для всех чатов — запрещён (UPD3 п.2).

## 5. Изменения схемы / каталога / env

- **Схема БД:** новых таблиц/колонок **нет** (per-chat — JSON `overrides` в существующем `chat_profiles`).
- **Каталог:** F2 сам **Δ=0** (перегруппировка/новая вкладка — в F3/ADR-1019-8). Меняются только **тексты описаний** четырёх ключей (`0`/`−1`-семантика + «безлимит») — включено в санкцию F3 (UPD3 принято).
- **env:** `config/settings.py:481-493` — новые дефолты (100 / 500 000; 60 / 300 000); `.env.example` — комментарий-плейсхолдер.

## 6. Влияние на тесты

- Новый `tests/test_budget_unlimited_round1019.py`:
  - `budget_state`/`is_unlimited`/`is_forbidden` (0/−1/25/«abc»);
  - `budget_exceeded`: calls-limit достигнут → `exceeded_metric='calls'`; tokens далеко → **не** exceeded; `0` → `forbidden`; `−1` → безлимит (не exceeded при любых used);
  - **семейная изоляция sentinel (итерация 2):** `budget_state(0)=='forbidden'`, `budget_state(-1)=='unlimited'`; `retention_state(0)=='eternal'`, `retention_state(180)=='cap'`, `retention_state(-1)=='invalid'` — три семейства **не** взаимозаменяемы (защита от «0=вечно» в бюджете);
  - per-chat override (`chat_params` mock) → per-chat лимит применяется; `chat_id=None` → глобальный; глобальный дефолт = 100/500 000 (не безлимит!);
  - **сид настроек чатов (F3 T-1859 — в F2 НЕ тестируется):** `apply_chat_settings_seed` пишет `−1` только целевому чату; повторный прогон — no-op; у другого чата значения **не меняются** (мультичатовая изоляция). В F2 проверяется лишь **механизм** per-chat override (`set_chat_params` + резолв); сам `services/chat_settings_seed.py` — F3;
  - **фон-контур (ревью-фиксы D-1/D-2):** `worker_budget` — `−1`=безлимит (расход пишется, `consume=True`), `0`=запрет, `>0`=cap; per-chat override действует; `allowed_workers` учитывает sentinel; дефолты `_metric_limit` = `settings.WORKER_DAILY_LLM_*_PER_CHAT` (60/300 000);
  - **fail-open (D-4):** при недоступном usage `budget_snapshot` сохраняет вычисленный `forbidden`/`source` (`0`-лимит виден без PG);
  - несовместимое состояние → ERROR-лог + `exceeded=False` (fail-open), sandbox не срабатывает.
- `tests/test_chat_keys.py` / `test_llm_client.py`: `details` содержит `unlimited`/`exceeded_metric`; sandbox — только при реальном отсутствии доступа; BYOK-фоллбэк цел; `llm_client` берёт `exceeded` и `details` из **одного** снимка (D-5).
- `tests/test_chat_usage.py` (если есть): `key_status` аддитивные поля.
- **Изоляция контуров:** тест, что лимиты `worker_budget._metric_limit`/`get_usage` резолвятся собственным ключом и не зависят от direct-бюджета `chat_usage` (ключи `limits.chat_global_key_budget_*`).
- `tests/test_param_catalog.py` — пин-тесты согласованы с F3 (Δ=0 у F2).
- R17: скан логов/`details` на отсутствие значений ключей. Полный `pytest` 0 failed; `git diff --check` clean.

## 7. Rollout / feature-flag / откат

- **Feature flag не вводится** (правка политики бюджета). «Безлимит» — это **данные**, не rollout-флаг.
- **Progressive delivery:** сначала тестовый чат `-1002661910336` (**сид настроек чатов**, ADR-1019-8 §D4) → проверка живого ответа → выборочно другие чаты по решению владельца (**только данными**, не сменой глобального дефолта).
- **Порядок:** F2 (механизм) → F3 (UI-тумблер, раздел, сид). Правки дефолтов применяются только после записи значений в PG (@DevOps/F3).
- **Rollback:** `git revert` + снятие per-chat override (вернуть 25/100000) → возврат к прежним лимитам.

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | **F-15 (10.3) §3.2/§6**: «0=запрет», «дефолты 25/100k не меняются», «sandbox штатно» | **SUPERSEDE/AMEND** ADR-1019-2 (владелец изменил требование) |
| R2 | «0=запрет» vs интуитивное «0=безлимит» | Явный sentinel `−1`; `0` не переиспользуется |
| R3 | Хардкод чата в коде | Запрещено; только данные; проверка @Reviewer |
| R4 | Per-chat резолв добавляет async-вызовы в горячий путь | `resolve_setting_cached` (TTL 120с, ADR-1018-7) |
| R5 | Правка `chat_usage` ломает бары Сводки worker-контура | T-1795 изоляция; F3 чинит отображение |
| R6 | Sentinel `−1` в UI выглядит непонятно | F3 рисует честный тумблер «Безлимит» (пишет `−1`) |

## 9. Открытые вопросы (human-gate — санкция владельца)

1. **(c) Семантика безлимита — ПОДТВЕРЖДЕНО (UPD3 п.2-3):** **`−1` (любое отрицательное) = безлимит; `0` = запрет** для **бюджетов** (канон F-7 сохранён осознанно; Δ механизма = 0, без новых ключей). Для иных семейств — свои sentinel-семантики (retention `0=вечно`, контекст `0=не задано`), см. §3.1/ADR-1019-8 §D2.
2. **(c) Новые прод-дефолты — ПОДТВЕРЖДЕНО как консервативные:** **100 вызовов / 500 000 токенов** (direct), **60 / 300 000** (фон per-chat). Безлимит — только per-chat (сид настроек чатов). §4.5.
3. **(c) Тексты каталога** (`0`/`−1`-пояснения, «Безлимит») — включены в санкцию F3 (UPD3 принято).
4. **Включение безлимита на проде** — **сид настроек чатов** `services/chat_settings_seed.py` для `-1002661910336` (или UI F3). Гарантия «без хардкода» — тест/ревью (id только в `config/chat_settings_seed.json` / миграции-данных).
