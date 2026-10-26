# RESIDUALS-ASAP23 — вердикты по остаточным строкам карт

Лейн: `RESIDUALS-ASAP23` (single writer). Worktree: `C:\Code\Python\adminbot-wt-res23`,
ветка `task/res23`, база `d3a9a2cc8ff22779c121e7c97a1432d42f13e6e4`
(release/p0-2026-10-26, прод 2.58.132). Дата: 27.10.2026.

Метод: по каждой строке сначала искалась поздняя принятая работа, уже
закрывающая приёмку (cite file:line + существующие тесты/evidence); код не
менялся, прод/SSH/Telegram/LLM не использовались. Запрещённые файлы
(`services/response_extent.py`, `tool_router.py`, `summary_memory.py`,
`direct_l1.py`) не трогались.

## Итоговая таблица

| Карта | Строка | Было | Стало | Основание (кратко) |
|---|---|---|---|---|
| asap2 | `MIGR-PAYLOAD` | PENDING | **VERIFIED** | эффективные байты L1 на проде == реальная runtime-сборка payload (фикстура P4 6542/c987c03e3ee0, CONTRACT-тест держит паритет); полная реконструкция маршрута без секретов: 0 вторых clarify-приказов; правила реально дошли до модели — платные прогоны r1 (45 кейсов) + r2 (19 вызовов HTTP 200) той же сборки тем же кодом |
| asap2 | `MIGR-HOTAPPLY` | PENDING | **VERIFIED** | цепочка hot-apply доказана кодом+тестами; живое наблюдение hot-apply на проде (cfg ADD-2.1: API-запись → немедленный эффект, NRestarts=0, PID 29475 до/после) на том же hot-слое (ConfigCache→hot.get), что и `resolve_prompt`; миграция канонов на проде без рестарта (release-103); ΔDDL=0 во всех релизах (user_version 37) |
| asap2 | `DONE-D6` | PENDING | **PENDING** (причина сужена) | 25/26 поведенческих классов §6 — живые прогоны действующей модели (r1+r2, вкл. T20-boundary, 4 вызова); T24 — service-level байт-паритет (24 passed). Остаток: живой T24 после рестарта + чтение `plan_meta needs_clar` с прода (инструментировано с 2.58.118: `direct_chat_service.py:343-349`, `usage_events.py:58`) — прод-чтения в evidence нет |
| asap3 | `MIG-SCOPES` | PENDING | **VERIFIED** | read-only проверка на проде выполнена (release-258114 §10): PG `style.policy` rev 12 — factory (dash.hard.factory синтез) и global (rules владельца) сверены с effective по `migration.md` §5; chat-документов стиля на проде нет → effective(chat)==global+factory подтверждён; механика chat-override — end-to-end тесты реального save-пути (S4/S5, 24 passed) |
| asap3 | `AUD-PROD-VERIFY` | PENDING | **VERIFIED** | создан консолидированный аудит-документ `evidence/audit-prod-verify.md`: матрица P1/P2/P3 × (код, активные PG, заводские, путь применения) со ссылками на уже принятые read-only аудиты 258113/258114/258118/258130 |

## 1. MIGR-PAYLOAD — CLOSED (VERIFIED)

Приёмка: «Показан эффективный итоговый model payload допустимого тестового
маршрута без секретов; в нём нет второго model-facing clarify=ask; актуальные
правила L1/L2 реально дошли до модели».

1. **Эффективный payload показан, без секретов.** Реальная runtime-сборка
   payload через действующий композер зафиксирована как CONTRACT-фикстура:
   `plans/features/_audit-2026-10-23/soul1-fixtures/after/direct-runtime-assembly-asap2.txt`
   (P4 = L1 planner SYSTEM 6542 симв., sha256-префикс `c987c03e3ee0`; P1/P2/P5 =
   L2 writer; сгенерировано офлайн-стендом `rerecord_asap2.py`, stub-LLM/память —
   секретов и приватных данных нет; методика и генеалогия — `soul1-fixtures/report.md` §2–4).
   Те же байты подтверждены как effective на проде:
   `evidence/prod-snapshot/report.md` §2/§4 (L1 effective = global PG = новый
   канон `c987c03e…`; L2 = factory `83ff62bbee40` при withheld).
   Байт-паритет фикстуры с текущим кодом держит
   `tests/test_soul1_composer_parity_off.py::test_p4_l1_planner_system_matches_recorded_dump`
   (прогон 27.10.2026 на этой базе: `-k matches_recorded_dump` → **4 passed**).
   Дополнительно полная реконструкция допустимого маршрута §6.3 #20 (L1 8559
   симв., L2 3165, `[СООБЩЕНИЕ]`×1) — `evidence/residual-verify.md` §4.
2. **Нет второго model-facing clarify=ask.** В собранных payload 0 вхождений
   `clarify=ask`, «Ничего кроме вопроса», «смысловой акт ответа: clarification»;
   секция канона «УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА» ровно 1 раз
   (`residual-verify.md` §4); инвариант Composer ON/OFF без второго приказа —
   `fix-r1/report.md` §B2/T33.
3. **Правила реально дошли до модели.** Платные живые вызовы той же модели, что
   на проде (`deepseek-v4-flash`), тем же кодом сборки: probe r1 — 45 кейсов
   (38/45, raw-JSON в `evidence/probe/raw/`), probe r2 — 19 вызовов, все HTTP 200
   (`evidence/probe-r2/ledger.jsonl`, sha `2b0619782b5e…`); поведение модели
   подтверждает контракт нового канона (T13/T15/T16 — один адресный вопрос по
   цели; T19/T21/T23 — продолжение исходной просьбы; 0 ложных/повторных
   уточнений). Байт-паритет сборки + совпадение effective-байтов прода ⇒
   в модель уходили именно актуальные правила.

Честная граница (не влияет на приёмку строки): литеральный дамп `messages[]`
изнутри работающего прод-процесса не снимался; телеметрия `plan_meta` с прода
не прочитывалась (см. DONE-D6). Все три демонстрандума приёмки закрыты
существующими принятыми артефактами.

## 2. MIGR-HOTAPPLY — CLOSED (VERIFIED)

Приёмка: «Hot apply/инвалидация кеша работают штатно; миграций схемы БД нет».

1. **Код-цепочка (hot-get без рестарта):** `resolve_prompt`
   (`services/prompt_style_blocks.py:333-352`, docstring: «Правка промпта в UI
   применяется без рестарта (hot-get)») → `hot_config.get`
   (`services/hot_config.py:71-76`) → `ConfigCache.set` = PG-апсерт + немедленная
   замена памяти под lock (`services/config_cache.py:681-708`); UI-save промптов
   идёт через `cache.set` (`web/api/speech.py:519,2876,3083`; `web/api/routes.py:891`).
2. **Инвалидация кеша chat_params:** запись → `pg_notify('chat_params_updated')`
   + локальная инвалидация (`services/chat_params.py:488-492`, кэш `:234-316`);
   кросс-процессный LISTEN на отдельном соединении (`bot.py:1265-1285`), TTL
   120 с как fail-open фолбэк.
3. **Тесты (прогон 27.10.2026, эта база):** `test_unified_core_route_coverage.py::test_hot_apply_changes_payload_without_restart`
   (1 passed), `tests/test_settings_worker_sync_round1018.py` (31 passed —
   notify-invalidate и fail-open), `tests/test_prompt_migrations.py` (43 passed —
   T34: миграция ровно 2 записи, повтор no-op, откат возвращает байты, hot
   `resolve_prompt` отдаёт новые каноны).
4. **Живое наблюдение hot-apply на проде (тот же hot-слой):**
   `plans/features/cfg/evidence/cfg-final/bindings.md` §ADD-2.1 + `ssh/probe-f1-summary.json`
   (sha `1feba46bd7d00b66`): API-запись burst 10→2 → `bot_settings=2`, PG fresh-read,
   немедленный отказ/возврат допуска, **NRestarts=0, PID 29475 до/после**; живые
   посты 28/28 «hot-reload 10→2→10 без рестарта» на 2.58.88 (`review-release-cfg01.md` §).
5. **Миграций схемы нет:** ΔDDL=0 во всех релизах линии — `PRAGMA user_version` 37
   до/после (release-258113/258118 deploy, `release-258130.md` §Deploy); миграция
   канонов L1/L2 применялась на проде «без git и без рестарта»
   (`cfg-07a/release/release-103/deploy.md` §), откат канонов — PREV-лестницы
   без рестарта (`release-103/review-rel.md`).

Граница: буквальный цикл «правка конкретного промпта в Inspector → следующий
turn» на проде не снимался; закрытие по альтернативе из собственного
next_check строки («service-level write→resolve с фиксацией отсутствия
рестарта») + живое наблюдение того же hot-слоя на проде.

## 3. DONE-D6 — остаётся PENDING (причина актуализирована)

Приёмка: «Сценарии §6 пройдены как семантические прогоны действующей модели и
интеграционные проверки; runtime словарей фраз/регулярок нет».

- Семантические прогоны действующей модели: **25/26** поведенческих классов —
  r1 (T01–T09, T12, T13, T15, T16, T19, T21, T23, T25) + r2 (T10, T11, T14,
  T17, T18, T22, T26 + парафразы) + T20-boundary (4 платных вызова,
  `probe-r2/raw/t20_boundary/`). Часть «без словарей/регулярок» — VERIFIED
  (DONE-D7, аудит диффа).
- Интеграционные проверки: T24 — байт-паритет payload при рестарте
  (`test_asap2_clar_contract.py:545-578`, 24 passed 27.10.2026); структурные
  T27–T31 и контрактные тесты в составе тех же 24.
- Остаток (честно): живой вариант T24 (restart реального процесса) и
  production-чтение `plan_meta needs_clar/clar_target_present`. Инструментация
  есть с 2.58.118 (`services/direct_chat_service.py:343-349` — два R17-safe
  bool; `services/usage_events.py:58` — whitelist), но ни один поздний релиз
  не публиковал read-only выборку `plan_meta` с прода → закрывать строку по
  телеметрии нельзя. Остаток закрывается одним read-only запросом
  `llm_usage_events` (module=direct_chat, step=l1_planner, план needs_clar) на
  следующем релизном окне либо живым T24-прогоном.

Статус в карте: **PENDING**, классификация `WAITING_EXTERNAL`, blocked_reason и
next_check обновлены под текущее состояние (прошлая формулировка «9 классов без
живого прогона» устарела после probe-r2).

## 4. MIG-SCOPES — CLOSED (VERIFIED)

Приёмка: «Настройки default/global/chat согласованы; эффективное значение
проверено на каждом уровне».

- **Прод, read-only (release-258114 deploy §10):** `SELECT style.policy` — rev 12,
  содержимое global-документа прочитано; заводской уровень сверен с effective:
  строки `dash` у владельца нет → синтез заводского `dash.hard.factory`
  (`enabled=True`) по коду `style_policy.py:947-970,1019` → «dash активен»;
  `hint_limits` отсутствует → OFF. Это и есть сверка effective по
  `migration.md` §5 (план §10.9 выполнен).
- **Chat-уровень:** chat-документов стиля на проде не существовало на момент
  аудита (в rev 12 только global; chat style docs none) ⇒ effective(chat) ==
  global+factory — что §10 и подтвердил. Механика chat-override проверена
  end-to-end на реальном save-пути: `test_s4_saved_limit_applies_next_resolve_without_restart`
  (реальный `chat_params.set_chat_params` → инвалидация → `effective_style_policy`),
  S5 изоляция чатов, S8 chat-правило тире, S9 Inspector = фактическая сборка
  global+chat (`tests/test_asap3_acceptance.py`; прогон 27.10.2026: 24 passed вместе
  с `test_asap3_style_hint_limits.py`).
- **Согласованность того же стека скопов на живых данных:** `diag aliases` на
  проде — chat-override (`uid=529151103`: chat=Папаха / global=Толян →
  effective=Папаха) при 39 сохранённых глобальных (release-258114 §11).

Граница (зафиксирована в карте): chat-level style-документ на проде не
проверялся SELECT'ом, поскольку таких документов нет; при появлении
владельческого chat-override достаточно одного read-only SELECT.

## 5. AUD-PROD-VERIFY — CLOSED (VERIFIED)

Приёмка: «Аудит-документ фиксирует фактический код, активные значения
PostgreSQL, заводские значения и реальный путь применения по каждому из трёх
дефектов».

Создан консолидирующий документ
`plans/features/asap3-corrective/evidence/audit-prod-verify.md` (матрица
P1/P2/P3 × 4 атрибута), который сводит ТОЛЬКО уже принятые факты:
- код: `evidence/style-phase1.md` §1.1–1.4, `evidence/limits-inventory.md`,
  `evidence/identity-phase.md`, `final-report.md` §2/§4/§5;
- активные PG: `release-258114/deploy.md` §10 (style.policy rev 12) и §11
  (diag aliases, 39 пользователей, chat-override effective);
- заводские: HINT_LIMIT_OFF=0, потолок 64, синтез `dash.hard.factory`,
  отсутствие ручного списка имён (binding-final grep);
- путь применения: `effective_style_policy` → `resolve_style_policy_ref` →
  композер → egress-verify; `set_chat_params`+NOTIFY+`bind_turn_aliases`;
  `compile_style_prompt` на проде (release-258130).

Новых обращений к прод в этой полосе не было — документ только
консолидирует зафиксированные ранее read-only факты.

## 6. Прогоны (27.10.2026, worktree task/res23, база d3a9a2cc)

| Набор | Результат |
|---|---|
| `pytest tests/test_asap3_acceptance.py tests/test_asap3_style_hint_limits.py -q` | **24 passed** (67 s) |
| `pytest tests/test_unified_core_route_coverage.py -k hot_apply -q` | **1 passed** |
| `pytest tests/test_settings_worker_sync_round1018.py -q` | **31 passed** |
| `pytest tests/test_prompt_migrations.py -q` | **43 passed** |
| `pytest tests/test_asap2_clar_contract.py -q` | **24 passed** |
| `pytest tests/test_soul1_composer_parity_off.py -k matches_recorded_dump -q` | **4 passed** |
| `py -3 -m compileall services` | rc=0 |
| Итого фокусированных | **127 passed, 0 failed** |

Предсуществующие падения (не этой полосой, на базовом d3a9a2cc):
`tests/test_soul1_composer_parity_off.py` — 4 ON-vs-legacy теста
(`test_tool_phase_on_*`, `test_l2_on_*`): ON-путь после p0-int R2 добавляет
слой `<Speech_Base>` (коммит-линия fe1e514a/d1a44592), а тесты требуют
«ON == legacy без новых слоёв». К записанным дампам P1–P5 отношения не имеет
(они pass). Классификация: `related-nonblocking` к SOUL-1/p0 картам — требует
перепринятия контракта ON-паритета владельцем слайса, не аспект asap2/asap3.

## 7. Что менялось в этом worktree

Код **не менялся**. Изменения: (1) новый документ
`plans/features/asap3-corrective/evidence/audit-prod-verify.md`; (2) этот файл;
(3) обновления двух карт (3 строки asap2, 2 строки asap3). Файлы
`services/response_extent.py`, `services/tool_router.py`,
`services/summary_memory.py`, `services/direct_l1.py` не открывались на запись.
