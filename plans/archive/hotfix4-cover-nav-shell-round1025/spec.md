# Хотфикс-4 `hotfix4-cover-nav-shell-round1025` — локальная спецификация

> **Раунд:** 10.25 (внеплановый, после hotfix3, перед F2). **Задачи:** T-2507…T-2528 (`tasks.md`).
> **Мастер-ТЗ:** `plans/current_task.md` (untracked — **не коммитить**, секреты не цитировать, R17/R18).
> **Тип:** backend (summary/prompts/канон) + web (CSS/shell/навигация/Telegram-init) + ops (деплой/верификация).
> **Статус:** Step 2 @Architect — спроектировано. Реализация — @Builder (Step 4).
> **ADR:** `adr-1025-8-cover-style-viewport-shell.md` (D1–D4).
> **Baseline (hotfix3):** HEAD `5f624cd` (код `cfe7342`), pytest **8041/0**, JS **22/22**, matrix 0, `database is locked`=0, APP_VERSION **2.58.3**.

## Инварианты (нарушать нельзя)
1. **Δ DDL = 0**; **Δ каталога = 0** — правки только **метаданных существующего** ключа `prompts.summary_cover_style` (группа/уровень/widget/видимость), новых ключей нет. Флаги — env-only `ClassVar`.
2. **Рабочий rich-путь/картинки не ломать**; правка канона промптов = код + эталон `plans/docs/canon/**` + `PREV_*`-слепок + миграции + тесты **одним** коммитом.
3. Не трогать F0/F1/hotfix/hotfix2/hotfix3-контракты, Эпик 2. R17: в логах — только маркеры/длины, без текста промпта/сообщений. Бэкапы/теги/`stash@{0}` не удалять.

---

## 1. [P0] A — применение настроенного стиля обложки (T-2508…T-2513)

**Установленный корень (проверено по коду):**
- Финальный промпт = `compose_cover_image_prompt(style, cover_prompt)` (`services/summary_generator.py:110-122`) — **стиль первым**, вызов `:757-759`, генерация `:769`; кап `SUMMARY_COVER_STYLE_MAX_CHARS` = **500** (`config/settings.py:609-610`).
- **Ключ в каталоге ЕСТЬ:** `prompts.summary_cover_style` (`services/param_catalog.py:412-413`, category `prompts`, group `prompts_summary`, `code_source=SUMMARY_COVER_STYLE_DEFAULT`, `widget=textarea` — `:1912-1918`). Значит `style_len=31` = дефолт `SUMMARY_COVER_STYLE_DEFAULT="photorealistic, cinematic light"` (`services/summary_prompts.py:153`) читается, потому что **в PG нет значения владельца** либо оно в **другом ключе/scope**, либо **перезаписывается** (code-default при отсутствии строки в `bot_settings`).
- **Конфликт:** `SUMMARY_EDITOR_COVER_PROMPT_BLOCK` (`services/summary_prompts.py:136-148`) прямо **запрещает** «текст, буквы, водяные знаки» → модель подавляет требуемый заголовок.
- **Баг доставки:** `_resolve_cover_prompt` (`:680-718`) при `draft is not None` (`:691-692`) **всегда** возвращает `draft.cover_prompt`; если он пуст — `""` → фолбэк hotfix3 **не срабатывает**, rich-обложка теряется.

**Решения (ADR-1025-8 D1):**
- **Диагностика (T-2508):** в R17-safe логе `summary cover: prompt composed` (`:765-768`) добавить маркеры `has_comic`, `has_heading`, `style_is_default` (сравнение с `SUMMARY_COVER_STYLE_DEFAULT`); **текст стиля/промпта не логировать**.
- **Гарантия применения (T-2509):** проследить путь `PG-строка bot_settings → hot.get(:757) → compose(:110)`; устранить потерю: (a) значение сохраняется под **верным** ключом `prompts.summary_cover_style`; (b) round-trip load→edit→save→**re-read**→compare; (c) никакой сид/миграция/дефолт не перезаписывает сохранённое. Дефолт — **только** когда значения реально нет.
- **Редактируемость (T-2510):** ключ виден и редактируем в Mini App (категория «Промпты», группа `prompts_summary`, textarea). Если рендер прячет группу — исправить **метаданные/рендер** (Δ каталога=0), сохранение — через F0 `persistItems`/`saveState` (не «тихий успех»).
- **Конфликт заголовка (T-2511):** смягчить `SUMMARY_EDITOR_COVER_PROMPT_BLOCK`: запрет надписей сохраняется для «чистого visual», **но явно разрешать короткий заголовок, заданный владельцем в стиле** (напр. «PERMsoc» / `heading`/`title`), если стиль этого требует. Атомарно: код + `plans/docs/canon/**` + `PREV_*` + миграция + тесты.
- **Баг пустого `cover_prompt` (T-2512):** в `_resolve_cover_prompt` при непустом `draft` и пустом `draft.cover_prompt` **не** возвращать `""` сразу — применить ту же ветку фолбэка (`_derive_fallback_cover_prompt` + kill-switch/`_rich_media_supported`); plain только с залогированной причиной.
- **Порядок/кап:** **оставить** `style → visual` (стиль владельца доминирует) и кап **500** (`SUMMARY_COVER_STYLE_MAX_CHARS`) — менять не требуется (pin-тесты `test_summary_cover_round1023/1024` не трогаем).

## 2. [P0] B — нижняя панель в пределах видимой области (T-2514…T-2518)

**Установленный корень:** `.bottom-nav { bottom: 0 }` (`web/static/app.css:1344-1348`) = низ **layout**-вьюпорта; `.app-shell { min-height: var(--tg-viewport-stable-height, 100vh) }` (`:679-683`) уже исключает нижний бар → панель уходит под него; компенсация только safe-area (`:1348`), а она на Android/Desktop = 0 (meta без `viewport-fit=cover`, `web/index.html:5`).

**Решение (ADR-1025-8 D2) — JS-offset + CSS-фолбэк:**
- `web/static/telegram-init.js`: вычислять и прокидывать **`--tg-viewport-bottom-offset`** = `max(0, window.innerHeight - viewportStableHeight)` (и учитывать inset-ы), обновлять на `viewportChanged`/`safeAreaChanged`/`contentSafeAreaChanged`. CSP-safe (без inline).
- CSS: `.bottom-nav { bottom: var(--tg-viewport-bottom-offset, 0) }` + **fallback** `bottom: max(0px, calc(100dvh - var(--tg-viewport-stable-height, 100dvh)))`; **симметрично** для `.more-sheet` (T-2515). Сохранить safe-area-паддинг (`:1348`) и тач-цель ≥44×44.
- `web/index.html:5`: добавить **`viewport-fit=cover`** (нужен для корректной safe-area на iOS); проверить, что раскладка iOS не ломается (риск — в §6).
- `tools/ui_round1025_matrix.py` (T-2517): вертикальная проверка для `.bottom-nav` (и `.more-sheet` при открытии) → **FAIL** при выходе за экран. Ловится **stable-инвариант** `rect.bottom <= stableHeight` (при симулированном системном нижнем баре `stableHeight = innerHeight − 56`) — именно он воспроизводит прод-дефект «панель под системным баром»; дополнительно проверяется `rect.bottom <= innerHeight + 1` как общий layout-контроль.

## 3. [P0] C — нижняя навигация: Статус и Справка первыми и для всех (T-2519…T-2521)

**Установленный корень:** `NAV_ITEMS_V2` (`web/app.js:328-343`) = `status, how, …`; но `bottomNavItems` (`:1358-1373`) для админа = `[status, modules, ai, more]` (**без `how`**), а `mobileMoreItems` (`:1376-1381`) содержит `how` → дубликат/неверный порядок.

**Решение (ADR-1025-8 D3):**
- `bottomNavItems`: **`status` + `how` — всегда первые два** (все роли, включая админов); далее **один** приоритетный админ-раздел (`modules`, иначе `ai`), затем «Ещё» — **лимит ≤4 пунктов** сохраняется. Если видимых админ-разделов нет — `[status, how]` (+«Ещё» только при наличии скрытых).
- `mobileMoreItems`: убрать дубликат `how`; оставить только реально скрытые (`memory`/`access`/`permsoc`, `ai` при вытеснении); «Ещё» не показывать, если скрытых нет.
- `services/param_catalog.py` и `sidebarGroups` **не трогать**; OFF-режим `IA_V2_ENABLED=false` — без изменений (legacy navbar).

## 4. Общее: тесты/версия/регресс (T-2522…T-2528)
- **T-2522:** синхронизировать `tests/test_ia_shell_round1025.py`, `tests/js/round1025_shell_breakpoints_test.js`, `tests/js/round1025_ia_routing_test.js`, ожидания matrix (`bottomNavCount` 2/3/4) — без ослабления.
- **T-2523:** bump `APP_VERSION` (2.58.3 → следующая; меняются `web/app.js`/`index.html`/`app.css`/`telegram-init.js`); обновить `?v=`-пины и README (pin-тест).
- **T-2524:** pytest 8041/0 (+новые), JS 22/22 (+новые), matrix 0, `database is locked`=0, `node --check`, `git diff --check`.
- **T-2525:** @Reviewer Approved; @Scanner 0 Critical/0 High (`plans/reports/round1025_hotfix4_scanner_audit.md`).
- **T-2526:** деплой (атомарные ru-conventional commits); **T-2527:** live-гейт владельца; **T-2528:** архивация + §56 ARCHITECTURE.

---

## 5. Точные точки изменения (file:line)
| Область | Файлы |
|---|---|
| A | `services/summary_generator.py:110-122,680-718,757-769`; `services/summary_prompts.py:136-153`; `services/param_catalog.py:412-413,1912-1918` (только метаданные); `plans/docs/canon/**`; тесты |
| B | `web/static/app.css:679-683,1344-1348` (+`.more-sheet`); `web/static/telegram-init.js`; `web/index.html:5`; `tools/ui_round1025_matrix.py`; тесты |
| C | `web/app.js:1358-1373,1376-1381`; F1-тесты/`round1025_shell_breakpoints_test.js` |
| Версия | `config/settings.py` (APP_VERSION) + `README.md`; `tests` `?v=`-пины |

## 6. Верификация
1. **A:** сохранённый непустой стиль доходит до `compose_cover_image_prompt` (`style_is_default=false`); при незаданном — дефолт; `has_comic`/`has_heading` в логе; «draft есть + пустой cover_prompt» → rich с обложкой (или plain с причиной); канон не запрещает требуемый заголовок; рабочий rich-путь не изменён.
2. **B:** `.bottom-nav`/`.more-sheet` целиком в экране (`rect.bottom <= innerHeight`) на 320/390/768 и на клиентах с нулевой safe-area; нет горизонтального overflow; тач ≥44×44.
3. **C:** для ролей user/admin/mixed первые два пункта — `status`+`how`; «Ещё» без дубля «Справки»; скрытые разделы достижимы; OFF-режим не изменён.
4. **Регресс:** pytest 8041/0 (+новые), JS 22/22, matrix 0, `database is locked`=0.

## 7. Риски и откат
| Риск | Ур. | Снятие |
|---|---|---|
| Стиль всё ещё теряется | Critical | T-2508 (маркеры) + T-2509 (round-trip) + T-2510 (UI-редактируемость) |
| Заголовок подавляется моделью | High | T-2511: явно разрешить заголовок в стиле; канон-правка атомарна |
| Тихая потеря обложки | High | T-2512: фолбэк при пустом `draft.cover_prompt` |
| Позиция панели зависит от клиента | High | T-2514/T-2516 (offset+фолбэк), T-2517 (matrix FAIL) |
| `viewport-fit=cover` ломает iOS | Medium | Проверить 320/390; при регрессии — откат только meta |
| Навигация: недостижимые разделы | High | T-2519/T-2520 (≤4, «Ещё» только при скрытых); H-1 Scanner не регрессировать |
| Секреты в логах | Critical | R17: только маркеры/длины (T-2508) |

**Флаги/откат:** новых kill-switch не требуется (конфиг/раскладка); `SUMMARY_COVER_FALLBACK_ENABLED` сохраняется. Откат — тег `pre-round1025-hotfix4` (T-2507) + `git revert` + возврат `APP_VERSION`.

## 8. Покрытие и ответы на open questions
T-2507→§0; T-2508…T-2513→§1 (ADR D1); T-2514…T-2518→§2 (D2); T-2519…T-2521→§3 (D3); T-2522…T-2528→§4 (D4). **Все 22 задачи покрыты.**

1. **Где стиль:** ключ в каталоге есть (`param_catalog.py:412-413`, group `prompts_summary`); причина — нет PG-строки/другой scope/перезапись → T-2509 (round-trip) + T-2510 (видимость в UI) + T-2508 (маркеры).
2. **Заголовок:** **явно разрешить** короткий заголовок владельца в стиле (T-2511), сохранив запрет надписей для «чистого visual».
3. **B-способ:** **JS `--tg-viewport-bottom-offset`** (primary) + CSS-фолбэк `max(0, calc(100dvh - var(--tg-viewport-stable-height,100dvh)))`; `viewport-fit=cover` — да (с проверкой iOS).
4. **C-слоты:** оставить **≤4**: `status`, `how`, (modules‖ai), «Ещё»; вытесненный `ai` — в «Ещё».
5. **Флаги:** достаточно `git revert`+`APP_VERSION` (kill-switch не нужен).

## 9. Ссылки
- `plans/features/hotfix4-cover-nav-shell-round1025/{tasks.md, adr-1025-8-cover-style-viewport-shell.md}`
- `plans/ARCHITECTURE.md` §54/§54.1 (F1/P0-fix), §55 (hotfix3); `plans/round1025-architecture.md`
- Отчёты: `round1025_hotfix3_scanner_audit.md` (при наличии), `round1025_f1_scanner_audit.md`
