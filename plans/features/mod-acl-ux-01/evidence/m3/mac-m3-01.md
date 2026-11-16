# MAC-M3-01 — design delivery evidence (M3, 2026-11-16)

**Статус:** evidence подготовлен для независимого ревью. `MAC-M3-01` и строки M3 **не**
переведены в `VERIFIED`; карта статусов, продуктовый код, тесты и конфигурация не изменялись.

**Локальное время сбора:** 2026-11-16 (UTC+12); production `/healthz` — 2.58.205.

## 1. Идентификаторы

| Поле | Значение |
|---|---|
| Плановая линия | `C:/Code/Python/adminbot`, `master` @ `ad587012` (на момент среза) |
| Deployed | **2.58.205 @ `bca18c1e271fdfafa4939b07c88a0d3f2a92b8a1`**, `release/vmq-slice-d-2.58.205` |
| Served `app.js` | 2 311 044 B, sha256 `3cf2c916…f594`, совпадает с checkout `bca18c1e` (M0) |
| Схема | `user_version=47`, DDL 0 (M0) |
| Каталог | 21 видимая карточка = 16 static + 5 registry-only; 11 `ModuleSpec` (10 visible + hidden) |
| Health | `https://admin-bot.duckdns.org/healthz` → `200 {"status":"ok","version":"2.58.205"}` |

## 2. Что проверено визуально

**Метод.** Из release-worktree `vmq-slice-d-release-…` @ `bca18c1e` поднят локальный сервер
`tools/ui_mod_acl_m4_embeddings_e2e.py --serve-only` (127.0.0.1:8871): реальные `web/index.html`,
`web/app.js`, `web/static/*`; `/api/config` — stub из deployed `registry_for_frontend()` и
`param_catalog` (629 items, 121 groups); TMA-идентичность — синтетический `TMA_STUB` (владелец
`5885953495`), не настоящая owner-сессия.

**Инструменты (оба обязательных):**

- **Playwright/Chromium** (Code Mode `browse`): 1280×800 и 390×844; маршруты `#/modules`,
  `#/modules` в chat scope, `#/modules/embeddings`, `.../settings`, `#/modules/web`,
  `#/modules/time`, `#/modules/experience`, `#/modules/summary`, `#/memory/rag`, `#/status`.
  Сняты DOM-тексты карточек, табов, шапки, aria-snapshot, `scrollWidth/clientWidth`.
- **Browser Use** (Code Mode `browseruse`): тот же каталог, 1707×932, `document.querySelectorAll(
  '[data-mod]').length = 21`, текст каталога прочитан независимо.

**Наблюдения (факты, не значения production):**

1. 21/21 `[data-mod]` видимы; порядок совпадает с M0.
2. Карточки без групп: 2 колонки по 500 px, высота 227–275 px; в первом viewport 1280×800 — 4
   карточки. Registry-карточки выше из-за длинных описаний (243–275 px).
3. Chat scope: у `summary/sleep/nostalgia/budgets/images/vision/experience` — бинарный checkbox
   `В этом чате выключен`; tri-state `Наследовать/Включить/Выключить` отсутствует. У
   `direct/factcheck/.../initiative/stories/character/random` — текст `В этом чате · управляется
   глобально Выключен` без контрола.
4. Модульная страница: H1 + subtitle + state + `Управляется из каталога →`, затем табы, затем
   `Обзор модуля` с **повтором** subtitle, generic-инструкцией и кнопкой `Открыть настройки
   модуля` (запрещённый owner §5.8 паттерн).
5. Breadcrumb модуля: `Статус / <Название>` вместо `Модули / <Название>`.
6. `#/modules/experience`: одновременно `Выключен` и `Работает` + `requested: выкл (…env-ось)` —
   противоречие из-за смешения `gate.requested` (global gate) и `items[].value` (chat item).
7. `#/modules/embeddings` в chat scope: `Работает` без подписи «Общий сервис»; `Основные настройки`
   начинаются с секретных ключей; `keys_llm` включает общие `keys.intel_*`/`keys.llm_*`, не только
   embedding-ключи; итог 25 params.
8. `#/modules/time`: H1 `Часовой пояс`, без табов, одно поле; корректный special case, но
   заголовок не совпадает с карточкой `Время`.
9. `#/memory/rag`: `memory.experience_learning_enabled` и другие submodule-ключи редактируются
   **и** на родителе, **и** на submodule-странице — второй write-point.
10. Статус: первый экран начинается с аналитики/карты, а не с health → пяти лент; это M4B, но
    подтверждает необходимость frozen §4.

**Ограничение.** `/api/config` — stub, значения синтетические (многие `false`); выводы сделаны
только о структуре, текстах, плотности и DOM-контрактах. Живой Mini App с owner `initData` не
открывался; production-значения флагов и права не читались. Это не блокирует M3 (design), но
является live-preflight для M4A/M6.

## 3. Артефакты M3

| Артефакт | Содержание | sha256 |
|---|---|---|
| `design-m3-2026-11-16.md` | design specification rev2: IA, 21 карточек, wireframes, состояния, API, responsive, token mapping, acceptance | `478BB0F2…45A68` |
| `copy-inventory.md` | полный copy inventory до/после, 401/403/404/503, пустота, 409 | `C1657BEB…8F369A` |
| `evidence/m3/catalog-1280.png` | каталог 1280×800, реальные deployed-ассеты + stub | `E19EDC1B…90D7E4` |
| `evidence/m3/catalog-390.png` | каталог 390×844 | `D0937AF9…C3386` |
| `evidence/m3/embeddings-1280.png` | «Векторная память» 1280×800 (текущее состояние) | `3143BCDD…6B4F9` |

## 4. Что зафиксировано (соответствие 20 строкам M3)

Полная таблица — `design-m3-2026-11-16.md` §11.1. Кратко:

- `MAC-S0-04` — 19 карточек GLOBAL+CHAT, 2 особые (Время, Векторная память); shared-инфраструктура
  без фиктивного master.
- `MAC-S0-07`, `MAC-AC-09` — design передан на независимое ревью; «тесты/скомпилировалось» не
  приёмка.
- `MAC-S2-89` — секреты/auth/Telegram/приватность/сеть не тумблеры.
- `MAC-S5-276…281` — короткие имена, одно предложение, термины в «Технических деталях», owner-
  ориентиры, сохранённый «чекап»/промпты, три сущности состояния, полный copy inventory.
- `MAC-AC-01`, `MAC-S3-CAT-01` — 21/21 + hidden `factcheck_temporal`: kind/scope/owner-ключ/
  consumer/control.
- `MAC-AC-05`, `MAC-S3-SHARED-01` — Embeddings/QRNG: общий сервис отдельно от chat-use; индексация
  и поиск — разные поля.
- `MAC-S3-TYPES-01` — типы по фактическому каталогу; 11 модулей требуют per-chat adapters.
- `MAC-S9-ARCH-01/02` — IA, wireframes, responsive, tokens, тексты, первый viewport; редакторская
  критика и удаление повторов/жаргона.
- `MAC-M3-01` — многостраничная навигация, карта экранов, Status/права без переписывания frozen §4/§5.
- `MAC-MX-01` — пересечения MEMORY-08/VMQ/SELF-DIAG/prompt/frontend и один владелец.
- `MAC-S13-ARCH-01` — точные компоновки/тексты на существующих полях, GLOBAL→CHAT без master-AND.

## 5. Блокирующие находки для M4A

1. **11 модулей не имеют per-chat runtime** (direct, factcheck, search, web, transcribe, video,
   media, checkup, stories, character, random): consumer читает `hot.get` глобально. Owner §3
   требует GLOBAL+CHAT. Нужен backend-срез **M2.1**; M4A не должен рисовать инертный tri-state.
   Доказательство — `reports/m2-consumers-dd52cbf9.md` §5–6 + точные файлы в design §12.2.
2. **`nostalgia` master precedence:** `feature_gates.FLAG_KEYS` может взять
   `flags.nostalgia_enabled` раньше `memory.nostalgia_enabled`; глобальный тумблер карточки станет
   инертным. Нужно `MASTER_FALLBACK_KEYS["nostalgia"]` или эквивалент + тест.
3. **`gate.source` vs `state.source`:** DTO не отдаёт источник значения и часть осей; UI получает
   ложные «Работает/Выключен». Нужен полный `state` в `gate_snapshot`.
4. **Дубли submodule-групп** на родителе и submodule-странице: один write-point через ссылку.
5. **`keys_llm` на embeddings** смешивает embedding- и общие ключи: фильтр `keys.embedding_*`.

## 6. Ограничения и честность

- Продуктовый код, тесты, `requirements-map.json`, `slice-graph.json`, `plan.md` не изменялись.
- `VERIFIED` не заявлен; независимый Reviewer M3 ещё не проверял композицию/тексты/адаптивность.
- Живые production-значения и owner-права не читались; live TMA — предусловие M4A/M6.
- Скриншоты — layout evidence, не доказательство значений флагов.
- Временные файлы стенда: сервер остановлен после снятия; исходные PNG остаются в
  `C:/Users/main/AppData/Local/Temp/opencode/acl_m3/`; в репозиторий добавлены три
  representative-снимка.

## 7. Изменённые файлы

| Файл | Что |
|---|---|
| `plans/features/mod-acl-ux-01/design-m3-2026-11-16.md` | design specification rev2 |
| `plans/features/mod-acl-ux-01/copy-inventory.md` | полный copy inventory |
| `plans/features/mod-acl-ux-01/m3-design-freeze.md` | датированное дополнение §8, история сохранена |
| `plans/features/mod-acl-ux-01/evidence/m3/mac-m3-01.md` | этот evidence |
| `plans/features/mod-acl-ux-01/evidence/m3/catalog-1280.png`, `catalog-390.png`, `embeddings-1280.png` | визуальные снимки (layout) |
