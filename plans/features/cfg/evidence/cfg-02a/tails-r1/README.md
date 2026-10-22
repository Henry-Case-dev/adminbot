# TAILS-R1 — CFG-02A harness (слайс CFG-02A, строки .3/.4/.5 + AC1)

Дата: **2026-10-22** (~05:30–06:05 UTC). HEAD `a7702559`. Прод/прод-конфиг не
тронуты; Telegram не использовался; платные вызовы провайдера: **0**
(фейковый генератор со счётчиком; прецедент test_cfg02a_image_quota_ui).

## Полный боевой контур quota-цепочки — `cfg02a-harness.json` (15/15 OK)

Реальные компоненты: POST/GET/DELETE `/api/config` (реальные роуты MiniApp —
тот же write-path, что `saveConfigItem`, включая optimistic 409→refresh+retry),
`ConfigCache` (реальный), `chat_params` (in-memory фейк namespace-семантики —
прецедент test_budget_overrides_merge_round1024), `worker_budget` reserve на
PG-стабе счётчиков (прецедент test_image_daily_limit_round1026), РЕАЛЬНЫЙ
каталог-резолвер `worker_settings` (чат → глобал → дефолт; `_metric_limit` НЕ
подменялся — подменён только env-атрибут shared-бюджета) и РЕАЛЬНЫЙ
direct-путь `ig.generate_and_send` с fake-провайдером.

### CFG-02A.4 (UI-изменение → worker_budget → разрешение/отказ)
- A1: UI write GLOBAL `limits.image_daily_limit=2` → 200;
- A2: `wb.image_limits` → (2, **global**) — бюджет считал новое значение;
- A3/A5: две генерации проходят; UI меняет 2→5 без рестарта — третья проходит;
- A6: usage-summary (расход 3) и каталог-лимит согласованы.

### CFG-02A.5 (квота исчерпана → отказ ДО платного вызова, честное время)
- B1: UI ставит 3 при расходе 3 → `generate_and_send` = отказ `budget`,
  **provider_calls = 0** (фейковый генератор не вызывался ни разу);
- B2: отказ несёт речевую форму SOUL-1 + фактическое время сброса;
- B3: `image_next_reset` = полночь **00:00 в TZ чата** (Asia/Yekaterinburg,
  2026-10-23T00:00:00+05:00) — не «24 часа от запроса» и не cooldown.

### CFG-02A.3 (GLOBAL — дефолт; разрешённый per-chat override сильнее)
- C1: GLOBAL=3 → оба чата (3, global);
- C2/C4: UI write override чату A =1 (200; override в store через write-path);
- C3: A=(1, chat), B=(3, global) — override сильнее, чужой чат не тронут;
- C5: «рестарт»-чтение (invalidation+fresh read) — override сохранён;
- C6: DELETE `/api/config/chat/<key>` → наследование GLOBAL, GLOBAL не
  изменён (значение 3 на месте).

### CFG-02.AC1 (модуль показывает квоту mobile/desktop) — `ui-e2e/`
- Существующий e2e-инструментарий `tools/ui_cfg02a_image_quota_e2e.py`
  (без правок; SHOTS/RAW редирект в tails-r1): **RESULT: PASS**, rc=0,
  console_errors=0; 6 канонических кадров + raw-журнал write-path.
- Дополнительные контрольные кадры на текущем HEAD: **ac1-desktop-1280x800.png**
  и **ac1-mobile-360x780.png** — секция «Лимиты генерации» с фактами квоты
  присутствует, горизонтального переполнения нет (`ac1-viewports.json`).

## Честные оговорки
- Storage-швы: chat_params и PG-счётчики — in-memory/стаб (прод-данные не
  писались; те же швы используют 27 тестов слайса); PG-persistency значения
  и счётчика закреплена тестами (`test_restart_keeps_used_and_limit`).
- Прод-байты UI не перезахватывались (существующая production-evidence
  release-25889 остаётся; web/ не менялся после неё — см. git log web/).
- Реальные генерации в Telegram-чате владельца — живое наблюдение класса
  owner_optional (не создавалось без необходимости).

## Запуск
`OPENCODE_WORKFLOW_SCRATCH/tails-r1/cfg02a_harness.py`,
`cfg02a_ac1_browser.py` (`.venv\Scripts\python.exe`).
