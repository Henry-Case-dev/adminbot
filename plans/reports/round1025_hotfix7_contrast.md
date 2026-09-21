# round1025 / hotfix7 — AA-доказательство контраста shell-слоя и карточек

- **Пакет:** `hotfix7-shell-glass-heartbeat-round1025` (T-2673…T-2677, ADR-1025-13 D3.6)
- **Закрывает:** требование UPD 4 «премиально и читабельно» + обязательную AA-таблицу новых серо-графитовых shell-токенов
- **Дата:** 22.09.2026 · **Метод:** ADR-1025-9 D4 / hotfix6 — композит токена поверх **худшей** фазы фона §10
- **Инвариант:** палитра §8 **не меняется**; при провале — повышать плотность подложки, а не палитру.

## Метод (worst-case)

- Худшая (самая светлая) фаза фона §10 = teal `--grad-a #42D6C4` при `opacity .30` (снижено с .42 в D3.5) над `--surface-0 #090D17`
  ⇒ wash ≈ **`rgb(26.1, 73.3, 74.9)`**.
- Эффективный фон — композит токена над wash. Для shell дополнительно посчитан **максимум specular-блика**
  (`--shell-specular` стартует с `rgba(255,255,255,.10)` в верхнем левом углу) — это пессимистичная оценка
  (блик градиентный; в реальности ≤.10 только у кромки).
- Токены: `--shell-bg rgba(33,37,45,.62)`, `--shell-bg-strong rgba(24,28,35,.90)`,
  карточки `--glass-bg rgba(21,27,42,.5)`, тултип `--glass-bg-strong rgba(21,27,42,.85)`.
- Порог WCAG AA для нормального текста (в т.ч. 10 px) = **4.5:1**; ratio — относительная яркость sRGB
  (та же формула, что `tools/ui_round1025_matrix.py::_contrast_rgb`).
- Эффективные фон-композиты:
  - `--shell-bg .62` → `rgb(30.4, 50.8, 56.4)`; +specular → `rgb(52.8, 71.2, 76.2)`;
  - `--shell-bg-strong .90` → `rgb(24.2, 32.5, 39.0)`; +specular → `rgb(47.3, 54.8, 60.6)`;
  - `--glass-bg .5` → `rgb(23.6, 50.1, 58.4)`;
  - `--glass-bg-strong .85` → `rgb(21.8, 33.9, 46.9)`.
- `--shell-texture` alpha ≤ .020 и faux-noise — на контраст не влияет значимо (учитывается в допуске ±0.1).

## Таблица: класс → эффективный фон → ratio → вердикт

| Класс текста | Токен цвета | Эффективный фон (композит) | Ratio | Вердикт |
|---|---|---|---|---|
| `.sidebar-link` (пункт меню, .85 rem) | `--text-2 #AAB6C8` | shell-bg .62 → `rgb(30.4,50.8,56.4)` | **6.46:1** | PASS |
| `.sidebar-link` — худший случай (макс. specular .10) | `--text-2 #AAB6C8` | shell-bg .62 + specular → `rgb(52.8,71.2,76.2)` | **4.73:1** | PASS |
| `.sidebar-link:hover` / `.more-item:hover` | `--text-1 #F4F7FB` | shell-bg .62 + hover `rgba(255,255,255,.06)` → `rgb(43.9,63.0,68.3)` | **10.27:1** | PASS |
| `.sidebar-link.active` / `.more-item.active` | `--text-1 #F4F7FB` | `--surface-3 #232E45` (непрозрачно) | **12.62:1** | PASS |
| `.bottom-nav-label` (**10 px**, нормальный текст) | `--text-2 #AAB6C8` | shell-bg .62 → `rgb(30.4,50.8,56.4)` | **6.46:1** | PASS |
| `.bottom-nav-label` — худший случай (specular .10) | `--text-2 #AAB6C8` | shell-bg .62 + specular | **4.73:1** | PASS |
| `.bottom-nav-link.active` (подпись+иконка) | `--text-1 #F4F7FB` | shell-bg .62 → `rgb(30.4,50.8,56.4)` | **12.34:1** | PASS |
| `.more-item` (шторка «Ещё») | `--text-2 #AAB6C8` | shell-bg .62 | **6.46:1** | PASS |
| `.more-item` — худший случай (specular .10) | `--text-2 #AAB6C8` | shell-bg .62 + specular | **4.73:1** | PASS |
| header — заголовок (`.header-title-wrap .text-sm`) | `--text-1 #F4F7FB` | shell-bg-strong .90 → `rgb(24.2,32.5,39.0)` | **15.26:1** | PASS |
| header — заголовок (худший случай specular .10) | `--text-1 #F4F7FB` | shell-bg-strong .90 + specular | **11.29:1** | PASS |
| header — имя пользователя (`.text-gray-300`) | `#D1D5DB` | shell-bg-strong .90 | **11.13:1** | PASS |
| header — второстепенный текст | `--text-3 #A2B0C6` | shell-bg-strong .90 | **7.46:1** | PASS |
| `.hb-tip` (тултип §15) | `--text-2 #AAB6C8` | glass-bg-strong .85 → `rgb(21.8,33.9,46.9)` | **7.86:1** | PASS |
| `.hb-tip b` (заголовок причины) | `--text-1 #F4F7FB` | glass-bg-strong .85 | **15.00:1** | PASS |
| Критический текст на стекле (`.text-red-400`) | `--err-text #FCA5A5` | glass-bg .5 (карточка) | **7.10:1** | PASS |
| Статус-метка WARNING на стекле | `--warn #F6C56F` | glass-bg .5 (карточка) | **8.43:1** | PASS |

**Итог:** **все проверенные shell- и карточные классы текста проходят AA ≥ 4.5:1** на худшей фазе фона,
включая пессимистичный максимум specular-блика и 10 px подписи нижней навигации.
Повышение плотности `--shell-bg`/`--shell-bg-strong` и изменение палитры §8 **не требуется**.
Снижение `body::before` opacity `.42 → .30` дополнительно **улучшает** контраст (фон темнее) — инвариант AA сохранён.

## Машинная проверка (автоматизация)

`tools/ui_round1025_matrix.py` (hotfix7, T-2681):
- `F7_PROBE_JS` снимает реальные computed-токены `--shell-bg`/`--shell-bg-strong`/`--glass-bg`,
  computed `background-color` shell-панелей и карточек и `body::before` opacity;
- `_hotfix7_failures()` даёт **FAIL**, если `--shell-bg == --glass-bg` (слияние слоёв), shell-panel
  `background-color` совпадает с карточным, `body::before` opacity > 0.32 (виньетка) или найден
  `backdrop-filter: url(`; проверяются normal и fullscreen.

## Ограничение честности

Композит аналитический (худшая фаза wash + пессимистичный specular). Реальный `backdrop-filter` в конкретном
WebView может давать иной усреднённый фон — окончательное подтверждение читаемости — live-гейт владельца (T-2682).
