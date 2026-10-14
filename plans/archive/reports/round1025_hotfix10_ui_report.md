# round1025 hotfix10 — UI-отчёт (T-2850/T-2859/T-2860/T-2861/T-2862)

- **Фича:** `hotfix10-liquidglass-rollback-shell-geometry-round1025` (ADR-1025-18, T-2843…T-2864).
- **Автор:** @Builder (Step 4). **Дата:** 2026-09-22.
- **Среда:** Chromium/headless (`tools/ui_round1025_matrix.py`, Playwright `.venv`), 10 вьюпортов, normal+fullscreen.
- **Итог:** `failures: 0`.

## 1. Набор 1 — БЕЗ библиотеки стекла (`UI_LIQUID_GLASS_LIB=OFF`, прод-default)

Отдельный Chromium-контекст (`ME_GLASS_OFF`) на 390×844 и 1280×800:

| Метрика | 390×844 | 1280×800 |
|---|---|---|
| `mountedCount` | 0 | 0 |
| `psTotal` (`.ps-glass*`) | 0 | 0 |
| поверхность `[data-glass-surface]` | 1 | 1 |
| тексты Сердцебиение/Бот/Сервер/CPU/RAM/Диск | все True | все True |
| селектор области нажимаем | True | True |
| canvas = viewport | 390×844 | 1280×800 |

Нижняя навигация (4 пункта, hit ≥44px, `elementFromPoint`) — H9-проба, failures 0. Fullscreen — canvas пересчитан, сердебиение видно.

## 2. Набор 2 — с библиотекой на ОДНОМ изолированном элементе

`H10_GLASS_ISOLATION_JS` (OFF→ON→unmount):

| Метрика | 390×844 | 1280×800 |
|---|---|---|
| `.ps-glass*` на функц. целях при ON | `[0,0,0]` | `[0,0,0]` |
| `.ps-glass*` в DOM при OFF | 0 | 0 |
| `.ps-glass*` после unmount | 0 | 0 |
| rects/`elementFromPoint` OFF↔ON | без изменений | без изменений |
| честный режим | `frosted` | `frosted` |

## 3. Фон (T-2861)

Пиксельные пробы `__AuroraFlow.sample()` через 0/5/10/20 с:
- 390×844: diffs `[16.51, 17.854, 11.63]`, mode `webgl`;
- 1280×800: diffs `[16.062, 18.797, 23.292]`, mode `webgl`.

Движение заметно за 5–10 с; canvas покрывает весь viewport (нет яркой вертикальной полосы слева / статичной заливки справа). CSS-градиенты поверх WebGL не добавлялись.

## 4. Честный режим (T-2850)

`glass.js::detectMode()` определяет источник преломления объективно — по фактическому слою `.ps-glass__refract`. Декоративная `[data-glass-surface]` источника не предоставляет → маркер `data-lg-mode="frosted"`; frosted **не** называется рефракцией. Рефракция маркируется только при наличии слоя преломления (проверено node-юнитом).

## 5. Live Telegram WebView — PENDING OWNER VERIFICATION (T-2862)

Живая проверка Telegram WebView (WebKit/Android/iOS) **НЕ проводилась**. Headless/Chromium-результаты **не выдаются** за WebView. Не воспроизводимо headless и остаётся владельцу:

- фактические `innerHeight` / `visualViewport.height` / `viewportHeight` / `viewportStableHeight` / `safeAreaInset.bottom` / `contentSafeAreaInset.bottom`;
- 4 пункта nav с подписями в реальной нижней safe-area;
- полноэкранный фон и FPS.

Статус не блокирует независимые задачи (UPD4 §8); визуальный дефект не объявляется устранённым только на основании сборки/вердикта Reviewer.
