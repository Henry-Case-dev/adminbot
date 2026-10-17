# W5 — статус рендер-проверки панели: **ЗАКРЫТА независимым ревью**

> **Итог (REVIEW-W5 §2, 17.10.2026):** рендер-проверка выполнена ревьюером и
> панель подтверждена; висевший здесь `PENDING` был **дефектом стенда
> Builder'а**, а не панели. Ниже сохранена история для аудита: сначала шаги
> Builder'а и точная причина, затем — что именно подтвердило ревью.

## Закрытие (REVIEW-W5 §2)

* Ревьюер поднял свой стенд (реальный `web/index.html`/`app.js` + полный
  набор JSON-стабов) и проверил панель **двумя независимыми инструментами**:
  * **Playwright (MCP):** якорь `[data-initiative-independent]` — ровно один;
    «Мониторинг интеллекта» сам вызывает `loadIntelFunnels` +
    `loadInitiativeVitality` (сетевые записи `/api/memory/intel-funnels`,
    `/api/memory/initiative-vitality`); в панели видны предупреждение
    «Возможности есть, сообщений нет», health-строка «тики: живые · прогонов:
    288 · отправок: 0», мягкие цели с границами, причины, «Мешает сейчас»,
    решения/отказы, доставка `message_id 987654 · Core 8f3ac1b2 ·
    Style 77ab90cd`, кнопка; клик → trace «Проверка без отправки в чат
    (mock)…»; 0 ошибок консоли; вьюпорты **390/320 — без горизонтального
    скролла**;
  * **Browser Use (реальный Chrome):** те же состояния подтверждены
    визуально; клик → тот же trace «прогон без публикации · LLM-вызовов: 1».
* Скриншоты ревьюера (scratch): `…\OpenCodeScratch\
  adminbot-ccef72c25768\w5_shots\review-w5-desktop.png`,
  `…-390-panel.png`, `…-320-panel.png`.
* **Точная причина прошлого PENDING (моя ошибка стенда):** сервер
  `_soul1_w5_visual_server.py` отдавал **404** на `/api/memory/stats`,
  `/api/memory/timeline`, `/api/memory/deep-sleep`, `/api/persona`; в
  `loadCognition` первый же `await` после `cognition/status` —
  `/api/memory/stats` — бросал исключение, управление уходило в `catch`, и
  `loadIntelFunnels`/`loadInitiativeVitality` не вызывались. С полным набором
  стабов цепочка проходит, панель рендерится.

**Статус строки:** `CLOSED` (Playwright + Browser Use, реальный Chrome).
Локальный процесс стенда `…_soul1_w5_visual_server.py 8791` остановлен при
FIX-W5.

---

## История (до закрытия)

## Что было сделано (реальные шаги, не «мок»)

1. Написан и запущен локальный визуальный сервер
   `tools/_soul1_w5_visual_server.py`: отдаёт **настоящий**
   `web/index.html` + `web/app.js` + `web/static/**` и подставляет
   JSON-стабы `/api/*` (в т.ч. `GET /api/memory/initiative-vitality` с
   полным W5-фикстуром: предупреждение `opportunities_no_messages`,
   причины, ворота с блокировками, решения/отказы, доставка с
   `message_id` 987654 и ревизиями Core/Style, мягкие цели, dry-run trace
   проверки).
2. Реальным браузером (Browser Use, CDP) поднята страница
   `…/web/index.html#/` (канонический маршрут Статуса; `#/status`
   нормализуется приложением) с внедрённым Telegram-стабом
   (`sessionStorage.adminbot.initData` + `window.Telegram.WebApp`).
3. Подтверждено живыми проверками в браузере:
   * страница открывается в админ-контексте: `/api/me` → `role_name:
     global_admin`, `is_global_admin: true`; видны admin-only блоки
     (`.exec-preview` → «Последний вызов», `.intel-card` → «Мониторинг
     Интеллекта», `.status-grid`, `[data-memory-tech]`);
   * `/api/status` содержит `intents.state = "ok"`;
   * `fetch('/api/memory/initiative-vitality')` из страницы → **200**,
     `activity.state = "opportunities_no_messages"`;
   * `fetch('/api/memory/intel-funnels')` из страницы → **200**;
   * `node tests/js/soul1_w5_initiative_panel_test.js` →
     `SOUL1-W5-PANEL-OK` (логика computed-полей панели, единственное
     место, `publish:false` по умолчанию, отсутствие `lg-lens`/`polymer` в
     новом markup).

## Чего не хватило Builder'у (точная причина, установлена ревьюером)

Якорь `data-initiative-independent` **не появился в DOM** в локальном
стенде: панель воронки рендерится под `v-if="initiativeFunnel"`, и в стабе
не воспроизвелись зависимости родительского контура «Мониторинг
Интеллекта». Точная причина (REVIEW-W5 §2): стенд отдавал **404** на
`/api/memory/stats` (и `/api/memory/timeline`, `/api/memory/deep-sleep`,
`/api/persona`), `loadCognition` падал на первом же `await` и не доходил до
`loadIntelFunnels`. Это дефект **стенда**, а не панели: разметка присутствует
в единственном экземпляре (`grep data-initiative-independent web/index.html`
→ 1), а логика вычисляемых полей проверена node-сторожем.

## Что оставалось и чем закрыто

1. **Playwright deterministic** (DOM/состояния) и **Browser Use rendered** —
   **выполнено ревьюером** (см. раздел «Закрытие» выше): панель отрендерена
   на реальном `web/index.html` со стабами данных, 390/320 без
   горизонтального скролла, клик по кнопке → mock-trace.
2. Альтернатива для локального стенда (на будущее): дополнить
   `tools/_soul1_w5_visual_server.py` стабами
   `/api/memory/stats|timeline|deep-sleep` + `/api/persona`, после чего кадры
   снимаются без прода.

**Статус строки: `CLOSED`** (не PENDING) — визуальное закрытие подтверждено
ревью; при следующих правках панели рендер-проверку повторять.
