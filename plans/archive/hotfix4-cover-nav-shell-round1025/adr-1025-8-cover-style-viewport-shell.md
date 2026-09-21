# ADR-1025-8 — Стиль обложки: применение, заголовок и фолбэк; позиционирование mobile-панели; порядок нижней навигации

- **Статус:** Proposed → (после деплоя) Accepted
- **Дата:** 2026-09-21
- **Раунд:** 10.25, внеплановый хотфикс **`hotfix4-cover-nav-shell-round1025`** (T-2507…T-2528)
- **Связано:** `spec.md`; ADR-1023-6 (cover article), **ADR-1025-7 D1** (обложка на fallback); `plans/ARCHITECTURE.md` §54/§55
- **Затрагивает:** `services/summary_generator.py`, `services/summary_prompts.py`, `services/param_catalog.py` (метаданные ключа), `plans/docs/canon/**`, `web/static/app.css`, `web/static/telegram-init.js`, `web/index.html`, `web/app.js`, `tools/ui_round1025_matrix.py`

## Контекст
1. **A:** прод-логи: `style_len=31` = дефолт `SUMMARY_COVER_STYLE_DEFAULT` (`services/summary_prompts.py:153`) вместо настроенного владельцем стиля (`in comic style … PERMsoc heading`). Ключ `prompts.summary_cover_style` в каталоге есть (`services/param_catalog.py:412-413`, group `prompts_summary`, `widget=textarea` — `:1912-1918`), значит значение в PG отсутствует/в другом scope/перезаписывается. Плюс блок Редактора (`summary_prompts.py:136-148`) запрещает «текст/буквы/водяные знаки» → заголовок подавляется. Плюс баг `_resolve_cover_prompt` (`summary_generator.py:691-692`): при непустом `draft` с пустым `cover_prompt` → `""`, фолбэк hotfix3 не включается.
2. **B:** `.bottom-nav { bottom: 0 }` (`app.css:1344-1348`) = низ layout-вьюпорта, а `.app-shell { min-height: var(--tg-viewport-stable-height) }` (`:679-683`) уже без нижнего бара → панель уходит за экран; safe-area = 0 на Android/Desktop (meta без `viewport-fit=cover`, `index.html:5`).
3. **C:** `bottomNavItems` (`app.js:1358-1373`) не содержит `how` для админа; `mobileMoreItems` (`:1376-1381`) содержит `how` → дубликат/неверный порядок.

## Решение

### D1 (A). Стиль владельца применяется; заголовок разрешён; пустой cover_prompt → фолбэк
- **Гарантия применения / scope (уточнено ревью итерации 2):** `prompts.*` — **per-chat-переносимые** ключи (`ParamSpec.per_chat`), поэтому Mini App в контексте выбранного чата сохраняет стиль в `chat_params.overrides` **этого чата** (`POST /api/config` + `X-Chat-Id`), а не в глобальный `bot_settings`; глобальный write-path (без `X-Chat-Id`) → `_post_config_global` → `cache.set_many` → `bot_settings`. Прежде саммари читало только глобальный `hot.get` → chat-scoped сохранение «терялось» (уходил код-дефолт). Резолв выровнен по паттерну алиасов (`summary_aliases.build_alias_resolver`): **override чата → глобальный `hot.get` → код-дефолт** (fail-open R6). Дефолт — только при реальном отсутствии значения. Сид — идемпотентный `ON CONFLICT (key) DO NOTHING`, ключ стиля **не входит** в канон-миграции промптов → сохранённое значение не перезаписывается. Ключ **виден и редактируем** в Mini App (Δ каталога=0 — новых ключей нет).
- **Заголовок:** Редактор Stage-1 не видит авторский «Стиль обложки» (он конкатенируется к image-промпту отдельно), поэтому блок `SUMMARY_EDITOR_COVER_PROMPT_BLOCK` сделан **self-contained** и без внутреннего противоречия: свои надписи не добавляем, короткий заголовок владельца задаёт сам стиль. Канон-правка атомарна (код + `plans/docs/canon/**` + `PREV_*` + миграция + тесты).
- **Фолбэк:** `_resolve_cover_prompt` при `draft != None` и пустом `draft.cover_prompt` переходит в существующую ветку `_derive_fallback_cover_prompt` (+kill-switch/`_rich_media_supported`); plain — только с залогированной причиной.
- **Порядок/кап:** оставляем `style → visual`; `SUMMARY_COVER_STYLE_MAX_CHARS=500` без изменений (pin-тесты не трогаем). Наблюдаемость: маркеры `has_comic`/`has_heading`/`style_is_default` (R17, без текста).

### D2 (B). Позиция панели: JS-offset с CSS-фолбэком
- `telegram-init.js` считает **`--tg-viewport-bottom-offset` = max(0, innerHeight − viewportStableHeight)** (с учётом inset-ов) и обновляет на `viewportChanged`/`safeAreaChanged`/`contentSafeAreaChanged`.
- CSS: `.bottom-nav`/`.more-sheet` — `bottom: var(--tg-viewport-bottom-offset, 0)` + fallback `max(0px, calc(100dvh − var(--tg-viewport-stable-height, 100dvh)))`; safe-area-паддинг и тач ≥44×44 сохраняются.
- `index.html`: `viewport-fit=cover` (iOS safe-area). Матрица: ключевой инвариант `rect.bottom <= stableHeight` (симулируется системный бар 56px) + `rect.bottom <= innerHeight` → FAIL.
- **Оговорка (review L10.25H4-4):** `viewport-fit=cover` глобальна (мета-тег один на всё приложение), ON/OFF-гейт невозможен. При `IA_V2_ENABLED=false` legacy-полоса `.navbar-band` **не** fixed-bottom и не имеет нижней safe-area-компенсации; это минорный iOS-визуал legacy-скоупа, принятый осознанно (компенсацию не добавляем, чтобы не трогать OFF-раскладку).
- **Почему не CSS-only:** без JS нельзя отличить layout-вьюпорт от stable-height на всех клиентах; JS-offset + CSS-fallback устойчивее.

### D3 (C). Нижняя навигация: публичные первыми, ≤4 слота
- `bottomNavItems` = `[status, how, (modules ‖ ai), more]` — `status`+`how` **всегда** первыми для всех ролей; лимит **≤4**; «Ещё» — только при наличии скрытых.
- `mobileMoreItems` = только скрытые (`memory`/`access`/`permsoc` + вытесненный `ai`); дубль `how` удалён. `param_catalog.py`/`sidebarGroups` не трогаются; OFF-режим `IA_V2_ENABLED=false` без изменений.

### D4. Флаги/инварианты
- Новых kill-switch не требуется: A — конфиг-дефект, B/C — раскладка/порядок; откат — тег `pre-round1025-hotfix4` + `git revert` + возврат `APP_VERSION`. `SUMMARY_COVER_FALLBACK_ENABLED` сохраняется. **Δ DDL = 0**, **Δ каталога = 0** (только метаданные существующего ключа).

## Последствия
**Positive:** владелец видит применение своего стиля и заголовка; обложка не теряется при пустом `draft.cover_prompt`; mobile-панель/шторка всегда в экране; «Статус»/«Справка» доступны всем и первыми.
**Negative/издержки:** HTTP-вариант `viewport-fit=cover` может изменить iOS-раскладку (проверить); канон-правка требует атомарной миграции; offset-переменная зависит от клиентских событий (CSS-fallback страхует).

## Альтернативы
| Альтернатива | Почему отклонена |
|---|---|
| CSS-only позиционирование | Не различает layout/stable-height на всех клиентах |
| Разрешить «любой текст» на обложке | Риск мусорных надписей; разрешаем только заданный владельцем короткий заголовок |
| Изменить порядок `visual → style` | Стиль владельца теряет приоритет; ломает pin-тесты |
| Слоты 5 (status/how/modules/ai/more) | Нарушает принятый лимит ≤4 и H-1-баланс |
| Новый kill-switch B/C | Избыточно для раскладки/порядка; `git revert` достаточен |

## Верификация
- A: `style_is_default=false` при сохранённом стиле; `has_comic`/`has_heading`; «draft есть + пустой cover_prompt» → rich; канон не запрещает заголовок; рабочий rich не изменён.
- B: `rect.bottom <= innerHeight` для `.bottom-nav`/`.more-sheet` на 320/390/768 и при нулевой safe-area.
- C: у ролей user/admin/mixed первые два — `status`+`how`; «Ещё» без дубля; скрытые достижимы.
- Регресс: pytest 8041/0 (+новые), JS 22/22, matrix 0, `database is locked`=0.

## Откат
Тег `pre-round1025-hotfix4` + `git revert`; возврат `APP_VERSION` при откате фронта. Бэкапы/теги/`stash@{0}` не удалять (R18).
