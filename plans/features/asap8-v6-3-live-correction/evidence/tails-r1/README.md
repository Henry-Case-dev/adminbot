# TAILS-R1 — asap8 harness/evidence (лейн TAILS-ASAP8-CFG-P0B)

Дата: **2026-10-22** (харнесс-окно 05:05–06:10 UTC). HEAD `a7702559` (прод
2.58.109 @ a1d8bd62). Прод и прод-конфиг не тронуты; Telegram не использовался
(FakeBot/локальные стабы); реальные provider-вызовы — только в окне 1.

## 1. Окно «Experience semantic» (V02 / REQ-B02-DOD / B10-R12) — `harness-experience.json` §window1

- **Провайдер:** 6 РЕАЛЬНЫХ вызовов OpenRouter (`deepseek/deepseek-chat-v3-0324`).
  ⚠️ Честная оговорка: прод-базовый `apinet.cloud` (deepseek-v4-flash) с
  dev-машины недостижим (ConnectTimeout, проверено probe_llm.py 21.10 evening
  → 22.10); harness-провайдер — OpenRouter. Контракт пробы — семантический
  конвейер (JSON-схема кандидатов, lesson lifecycle), а не конкретная модель.
- **detector_detected = 0** — все captured-кандидаты семантические (regex-
  детектор не сработал ни на одной формулировке; формулировки подобраны вне
  `_PREFERENCE_RULES`/`_CORRECTION_PATTERNS`/`_FACT_USER_PATTERNS`).
- **4/4 сценария захвачены** (participant_correction, semantic=true):
  multi_msg_pref → `message.length_short`; fact_correction → correction →
  `failure_pattern`; indirect_style → `format.lists_no`; dont_repeat →
  `topic.currency_no`. 4 активных урока (валидация без ручной разметки).
- **Применение при повторе (V02):** retrieval на повторную ситуацию — 3 урока
  отобраны тем же semantic gate боевого пути; record_applications=3;
  outcome success → **lesson_counters_success=1** (genuine lesson applied).
- **Отбраковка (B02):** шутка/слух/несогласие (формулировки без маркеров) →
  ни одного нового урока; 1 честный `semantic_parse_error` в счётчиках.
- Что осталось честным хвостом: прод-метрики scanned/semantic из боевого
  потока и «1 доказанный lesson из боя» — наблюдение естественного потока
  (не производится по запросу; pet-project standing rule).

## 2. Окно «Memory historical RAG» (V03 / REQ-B03-DOD) — §window2

- 0 provider-вызовов (синтетические векторы, прецедент B03-тестов/B10-R13);
  **все 5 проверок OK**: свежий RAG не выдаёт истёкшее; исторический запрос
  (include_archived — путь dig_into_lore) находит; архивный факт попадает в
  relevant context с датой; refute меняет temporal статус без delete (rows
  unchanged); refuted не в свежем RAG, но виден исторически.
- Оговорка: контур FTS (боевой режим при деградированных эмбеддингах —
  ровно текущее состояние прода); векторная часть покрыта B10-R13 (16 005
  vec-строк, foreign_leak=0).

## 3. B10-R14 — overrides map + Random toggle, 2 чата (`overrides-r14-harness.json`)

Реальные роуты POST/GET `/api/config`, `GET /api/config/overrides-map` (тот же
write-path, что saveConfigItem) + реальный ConfigCache; chat-слой — in-memory
фейк namespace-семантики (прецедент round1024); 5/5 проверок OK:
UI write 2 ключей чату A (включая `memory.random_enabled` — D08 Random
toggle) → чтение назад (A: source=chat, B: global) → overrides-map (A в
карте с обоими ключами, B отсутствует) → «рестарт»-чтение store (значения
A целы, B не изменился). Оговорка: PG-persistency глобального слоя закреплена
тестами (`test_d08_write_makes_item_persistent`, `test_restart_keeps_used_and_limit`).

## 4. B10-R15 — Dream/Deep Sleep при включённом гейте (`dream-gate-on-harness.json`)

Локальный harness-конфиг (персистентный прод-конфиг не тронут), FakeLLM,
0 provider-вызовов; 2/2 проверок OK:
- Dream gate ON → run_once: **distilled=2**, deferred=1, watermark,
  memory_dream_log с честными run_at/статусами — «фактические изменения»
  существуют при включённом продюсере;
- Deep Sleep gate ON → стадии bridge/validate/write = succeeded,
  **written=1**, report в mca_pipeline_runs с timestamp.
- Прод-контур по умолчанию producer_off — честный zero по дизайну; артефакт
  при гейте ON больше не отсутствует.

## 5. B10-R19 — видео изгиба линии (`glass-video/`)

- `glass-line-bend.webm` (~0.7 МБ, 1280×800, реальный Chrome channel) +
  6 уникальных PNG-кадров (фазы волны под линзой; sha в meta.json) +
  meta.json: probe **tierA=true (probe-chromium, engine=chromium, svg=true,
  backdrop=true)**, console_errors: 1 (404 favicon — не продукт).
- Стек байт-неизменен: glass.js `76fc5e15`, glass-refraction.js/glass-probe.js
  `0ca661fe` (git log — позже этих коммитов файлы не менялись; HEAD a7702559).
- Стенд `tests/glass-teststand/glass-teststand.html?bg=wave`, волна
  осциллирует под статичным Tier-A слоем — изгиб линии виден на видео и
  кадрах. Физический FPS на реальном устройстве — добровольное
  device-наблюдение (вне RFL, U07-OWNER-REALDEV-класс).

## Запуск

Скрипты в `OPENCODE_WORKFLOW_SCRATCH/tails-r1/` (не в репо):
harness_experience.py, overrides_r14_harness.py, dream_gate_on_harness.py,
glass_video.py (+ probe_llm.py/probe_alt.py — выбор провайдера).
Повтор: `.venv\Scripts\python.exe <script>`.
