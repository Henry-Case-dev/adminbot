# MAC-M3-01 — design delivery evidence (M3, rev2.1, 2026-11-16)

**Статус:** evidence подготовлен для независимого ревью. `MAC-M3-01` и строки M3 **не**
переведены в `VERIFIED`; карта статусов, продуктовый код, тесты и конфигурация не изменялись.
Ревизия 2.1 закрывает замечания ревью (E1 + D1–D12), но не заменяет повторное независимое ревью.

**Локальное время сбора:** 2026-11-16 (UTC+12); production `/healthz` — 2.58.205.

## 1. Идентификаторы

| Поле | Значение |
|---|---|
| Плановая линия | `C:/Code/Python/adminbot`, `master` @ `ad587012` (на момент среза) |
| Deployed | **2.58.205 @ `bca18c1e271fdfafa4939b07c88a0d3f2a92b8a1`**, `release/vmq-slice-d-2.58.205` |
| Served `app.js` | 2 311 044 B, sha256 `3cf2c9168c350f49977127a1e6bb19363734e27923efeeeae4bce9fa9895f594`, совпадает с checkout `bca18c1e` (M0) |
| Схема | `user_version=47`, DDL 0 (M0) |
| Каталог | 21 видимая карточка = 16 static + 5 registry-only; 11 `ModuleSpec` (10 visible + hidden) |
| Health | `https://admin-bot.duckdns.org/healthz` → `200 {"status":"ok","version":"2.58.205"}` |
| Артефакты design | design + copy — коммит **`cc060b7631bfcd3be0ef53db821f23facda857e1`**; freeze — коммит **`36f3e603039de199ff4aea4b6e4fd4a29b0ec9f1`**; хеши §3 сняты после последней правки и совпадают с блобами на `HEAD` |

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

1. 21/21 `[data-mod]` видимы; порядок совпадает с M0 (16 static + 5 registry-only).
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

**Дополнительно для rev2.1 (сверка «до», без нового прогона):** реальные строки шапки каталога —
`Найти модуль…`, фильтры `Все`/`Включённые`/`Выключенные`/`Есть проблемы`, счётчик
`Показано 21 из 21 · здоровье показывается там, где для модуля есть данные`, загрузка
`Загружаем каталог модулей…` (`web/index.html`, deployed `bca18c1e`). Вкладки карточек и их
подписи — `WORKSPACE_TABS` + `WORKSPACE_TAB_LABELS` + `WORKSPACE_TAB_LABELS_OVERRIDES`
(`summary` 10, `direct` 8, `media_download` 3, registry-only — `overview/settings`). Зона
«Расширенные» и её носитель проверены по `param_catalog.REGISTRY` (645 params,
`progressive_level`, `_ADVANCED_GROUPS`): advanced-параметры есть у `sleep`, `nostalgia`,
`initiative`, `character`, `experience`, `random`.

**Ограничение.** `/api/config` — stub, значения синтетические (многие `false`); выводы сделаны
только о структуре, текстах, плотности и DOM-контрактах. Живой Mini App с owner `initData` не
открывался; production-значения флагов и права не читались. Это не блокирует M3 (design), но
является live-preflight для M4A/M6.

## 3. Артефакты M3

Хеши сняты **после** финальной правки rev2.1. Колонки: `git blob` — id блоба файла на `HEAD`
(проверяется `git rev-parse HEAD:<path>`); `sha256` — хеш содержимого файла (полный).

| Артефакт | Содержание | git blob | sha256 |
|---|---|---|---|
| `design-m3-2026-11-16.md` | design specification rev2.1: IA, 21 карточка, per-card матрица, wireframes, состояния, API, DTO-имена, responsive, token mapping, acceptance, M2.1 | `cad07c07c67c9999fc1edbd28225504525ffc40d` | `1b363dafe25a16ceeaa62dc336228b26220eac7a0cec7ecbf77b7a6d80a65a3f` |
| `copy-inventory.md` | полный copy inventory до/после: карточки, вкладки, управление, состояние, пустота, 401/403/404/503, 409, шапка каталога (§10), границы Статуса/Прав (§11) | `cc0b25b60ed4100c90e876217d5283d9a83e312c` | `f93e7573be60a7cbf099e40f96c12d751a2bb0a47787ff0daac3c14a16cb699e` |
| `m3-design-freeze.md` | frozen §1–§7 + датированные дополнения §8 (rev2) и §9 (rev2.1) | `113ca5b1034c597d92c5abf5b2bfe8fd2d94a0be` | `e799224a86d21758404ed88f87c752078463f53409f1c32eb3fdffe16e4b4fd6` |
| `evidence/m3/catalog-1280.png` | каталог 1280×800, реальные deployed-ассеты + stub | `9283dd07de745deb8832396f67375ff6f036d1c1` | `e19edc1b78cace5af036cc74f32cc733042cdc7d7d5ab3166d1a3fa8f090d7e4` |
| `evidence/m3/catalog-390.png` | каталог 390×844 | `3e159d84f7f394516b242149c48dcd053ba34950` | `d0937af90002efb83e98ff614b93b9d8bad09d1c2fa6201776b248c5956c3386` |
| `evidence/m3/embeddings-1280.png` | «Векторная память» 1280×800 (текущее состояние) | `30d8271a47bf38bbe55a90dccebe3b495af44153` | `3143bcddadc3f54bb38be17f1aebb41b927a826c41c031fb1b5db140c596b4f9` |

**Как проверить (машинально):**

```text
git rev-parse HEAD:plans/features/mod-acl-ux-01/design-m3-2026-11-16.md
# → cad07c07c67c9999fc1edbd28225504525ffc40d
sha256sum plans/features/mod-acl-ux-01/design-m3-2026-11-16.md
# → 1b363daf…0a65a3f  (Windows: Get-FileHash -Algorithm SHA256)
```

Хешей «до правки» в evidence нет: предыдущие значения (`478BB0F2…`, `C1657BEB…`) не совпадали ни с
одним коммитом design и заменены значениями выше.

## 4. Что зафиксировано (соответствие 20 строкам M3)

Полная таблица — `design-m3-2026-11-16.md` §11.1 (ссылки на разделы сверены в rev2.1). Кратко:

- `MAC-S0-04` — 19 карточек GLOBAL+CHAT, 2 особые (Время, Векторная память); shared-инфраструктура
  без фиктивного master.
- `MAC-S0-07`, `MAC-AC-09` — design передан на независимое ревью; «тесты/скомпилировалось» не
  приёмка.
- `MAC-S2-89` — секреты/auth/Telegram/приватность/сеть не тумблеры.
- `MAC-S5-276…281` — короткие имена, одно предложение, термины в «Технических деталях», owner-
  ориентиры, сохранённый «чекап»/промпты, пять осей + `source`, полный copy inventory.
- `MAC-AC-01`, `MAC-S3-CAT-01` — 21/21 + hidden `factcheck_temporal`: kind, `runtime_gate`,
  owner-ключ, consumer, control; per-card матрица вкладок и источников — §2.4.
- `MAC-AC-05`, `MAC-S3-SHARED-01` — Embeddings/QRNG: общий сервис отдельно от chat-use; индексация
  и поиск — разные поля.
- `MAC-S3-TYPES-01` — типы по фактическому каталогу; 12 модулей требуют per-chat adapters (M2.1).
- `MAC-S9-ARCH-01/02` — IA, wireframes, responsive, tokens, тексты, первый viewport; редакторская
  критика и удаление повторов/жаргона.
- `MAC-M3-01` — многостраничная навигация, карта экранов, Status/права без переписывания frozen §4/§5.
- `MAC-MX-01` — пересечения MEMORY-08/VMQ/SELF-DIAG/prompt/frontend и один владелец.
- `MAC-S13-ARCH-01` — точные компоновки/тексты на существующих полях, GLOBAL→CHAT без master-AND.

## 5. Блокирующие находки для M4A

1. **12 модулей не имеют честного per-chat runtime** (`mod_initiative`, `mod_direct`,
   `mod_factcheck`, `mod_search`, `mod_web`, `mod_transcribe`, `mod_video_summary`,
   `mod_media_download`, `mod_checkup`, `mod_stories`, `mod_character`, `mod_random`): owner §3
   требует GLOBAL+CHAT. **Решение:** M2.1 — отдельный backend-срез, обязательный предшественник
   M4A; до его закрытия M4A не рисует CHAT-контролы этих 12, interim disabled-контрол не нужен.
   Доказательство — `reports/m2-consumers-dd52cbf9.md` §5–6, точные файлы — design §12.2.
2. **`runtime_gate` объявлен неверно у 8 спецификаций** (`initiative`, `stories`, `character`,
   `random`, `factcheck`, `vision`, `nostalgia`, `sleep` — все `global`): исправляются на
   `per_chat` в `services/module_registry.py` (M4A, после M2.1). `summary`/`budgets`/`images`
   спецификаций не имеют и создаются сразу с `per_chat`; `experience` уже `per_chat`.
3. **`nostalgia` master precedence:** `feature_gates.FLAG_KEYS` может взять
   `flags.nostalgia_enabled` раньше `memory.nostalgia_enabled`; глобальный тумблер карточки станет
   инертным. Нужно `MASTER_FALLBACK_KEYS["nostalgia"]` или эквивалент + тест (M2.1).
4. **`gate.source` vs `state.source`:** DTO не отдаёт источник значения и часть осей; UI получает
   ложные «Работает/Выключен». Нужен `state` из `feature_gates.gate_state` (design §6.2 п.2–3).
5. **Дубли submodule-групп** на родителе и submodule-странице: один write-point через ссылку.
6. **`keys_llm` на embeddings** смешивает embedding- и общие ключи: фильтр `keys.embedding_*`.

## 6. Ограничения и честность

- Продуктовый код, тесты, `requirements-map.json`, `slice-graph.json`, `plan.md` не изменялись.
- `VERIFIED` не заявлен; независимый Reviewer M3 ещё не проверял rev2.1.
- Живые production-значения и owner-права не читались; live TMA — предусловие M4A/M6.
- Скриншоты — layout evidence, не доказательство значений флагов.
- Цифры первого viewport в design §2.4 — расчёт по константам §4.1 (topbar 56, шапка 168,
  карточка 148, gap 16), а не измерение нового макета; измеренный baseline — 4 карточки при
  1280×800. Проверка нового макета — M4A (Playwright, 5 viewport), не M3.
- Наличие advanced-параметров проверено программно по `param_catalog.REGISTRY` из checkout
  `bca18c1e`; отдельного прогона UI для зоны «Расширенные» не делалось (она уже рендерится
  существующим `advancedItems`).
- Временные файлы стенда: сервер остановлен после снятия; исходные PNG остаются в
  `C:/Users/main/AppData/Local/Temp/opencode/acl_m3/`; в репозиторий добавлены три
  representative-снимка.

## 7. Изменённые файлы

| Файл | Что |
|---|---|
| `plans/features/mod-acl-ux-01/design-m3-2026-11-16.md` | design specification rev2 → rev2.1 (замечания ревью) |
| `plans/features/mod-acl-ux-01/copy-inventory.md` | copy inventory rev2.1: §10 шапка каталога, §11 границы Статуса/Прав, `source` как атрибут, `permissions.*` |
| `plans/features/mod-acl-ux-01/m3-design-freeze.md` | дополнения §8 (rev2) и §9 (rev2.1); история §1–§7 сохранена |
| `plans/features/mod-acl-ux-01/evidence/m3/mac-m3-01.md` | этот evidence (rev2.1) |
| `plans/features/mod-acl-ux-01/evidence/m3/catalog-1280.png`, `catalog-390.png`, `embeddings-1280.png` | визуальные снимки (layout) |

## 8. Ревизия 2.1 — что закрыто

| # | Закрытие |
|---|---|
| E1 | хеши §3 пересчитаны от фактических коммитов (`cc060b76…` — design/copy, `36f3e603…` — freeze), git blob + sha256 после финальной правки; «до правки» удалены |
| D1 | design §2.4: per-card матрица 21 карточки (tabs/подписи, История/События, «Расширенные», default, viewport 1440/1280/768/390/320); `history_source` в DTO |
| D2 | design §6.2 п.1: 8 `runtime_gate` (`initiative`, `stories`, `character`, `random`, `factcheck`, `vision`, `nostalgia`, `sleep`); summary/budgets/images — новые спеки; передача M2.1/M4A — §12.5 |
| D3 | design §6.2 п.3: `feature_gates.gate_state`/`CapabilityState`, `global_value/source` из `FLAG_KEYS`, param как default/usage, один чатовый контрол |
| D4 | design §12.2 (12 id), §12.5.1/12.5.2, §12.6 п.5: M2.1 — отдельный срез-предшественник; CHAT-контролы только после него |
| D5 | copy §10 (шапка/фильтры/счётчик/пусто/загрузка) и §11 (Статус/Права: frozen §4/§5 + редактура §6); design §7.4 |
| D6 | design §3.2: `catalog_order` 1…21 нормативен; регистрация не влияет; инвариант DOM == `catalog_order` |
| D7 | design §2.2/§3.2: чип `Часть «PERMsoc»` для «Характера» (`parent_id=persona`) |
| D8 | design §11.1: ссылки исправлены (MAC-S2-89 → §2.2/§6.4; MAC-S5-279 → §7.1 + copy §9; MAC-AC-05 и MAC-S3-SHARED-01 → §4.4/§6.3) |
| D9 | design §5.1: пять осей + `source` как атрибут `desired`; copy §4 согласован |
| D10 | design §6.2 п.1–2: `runtime_gate` — одно имя в `ModuleSpec` и DTO (`scope` — только контекст), `permissions{can_read,can_edit}` — единственное место, `state` вместо `usage_state` (`service_state` только infra) |
| D11 | design §2.5: `status_source`/`help_anchor`/`rationale` для 11 новых `ModuleSpec` + правило вывода |
| D12 | design §3.3 (один заголовок), §4.1 (контент = viewport − sidebar − 48, 4/3/2/1), §8 (WCAG 1.4.1), §9 (state-чип), §10 п.13–15, §11.2 п.3/8 |
