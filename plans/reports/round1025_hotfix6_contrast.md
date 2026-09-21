# round1025 / hotfix6 — AA-доказательство контраста новых стеклянных панелей

- **Пакет:** `hotfix6-webview-shell-heartbeat-round1025` (T-2588…T-2592, ADR-1025-12 D2)
- **Закрывает (High):** «нет AA-доказательства по новым полупрозрачным панелям»
- **Дата:** 22.09.2026 · **Метод:** ADR-1025-9 D4 — композит `--glass-bg` поверх худшей фазы фона §10
- **Инвариант:** палитра §8 **не меняется**; при провале — повышать плотность подложки, а не палитру.

## Метод (worst-case)

- Худшая (самая светлая) фаза анимированного фона §10 = teal `--grad-a #42D6C4` при `opacity .42` над `--surface-0 #090D17`
  ⇒ wash ≈ `rgb(33, 97, 96)` (phase-teal).
- Эффективный фон панели:
  - панели на `--glass-bg rgba(21,27,42,.5)` → **`rgb(27, 62, 69)`** (совпадает с `GLASS_EFF_WORST` матрицы);
  - шапка/плотные слои на `--glass-bg-strong rgba(21,27,42,.85)` → **`rgb(23, 38, 50)`**.
- Порог WCAG AA для нормального текста (в т.ч. 10 px) = **4.5:1**; ratio считается по относительной яркости (sRGB),
  той же формулой, что `tools/ui_round1025_matrix.py::_contrast_rgb`.
- `backdrop-filter: blur(16px)` только размывает фон — усреднение не может сделать подложку светлее худшей фазы wash,
  поэтому аналитический worst-case консервативен.

## Таблица: класс → эффективный фон → ratio → вердикт

| Класс текста | Токен цвета | Эффективный фон (композит) | Ratio | Вердикт |
|---|---|---|---|---|
| `.sidebar-link` (пункт меню, 0.85 rem) | `--text-2 #AAB6C8` | glass-bg .5 → `rgb(27,62,69)` | **5.61:1** | PASS |
| `.sidebar-link:hover` / `.more-item:hover` | `--text-1 #F4F7FB` на hover-overlay `rgba(255,255,255,.06)` | → `rgb(40,74,80)` | **8.96:1** | PASS |
| `.sidebar-link.active` / `.more-item.active` | `--text-1 #F4F7FB` | `--surface-3 #232E45` (непрозрачно) | **12.62:1** | PASS |
| `.sidebar-brand` / `.sidebar-label` (текст) | `--text-1 #F4F7FB` | glass-bg .5 → `rgb(27,62,69)` | **10.71:1** | PASS |
| `.sidebar-sep` / `.more-sheet-handle` (декор) | `--surface-border` (декоративно, не текст) | glass-bg .5 | n/a | не текст |
| `.bottom-nav-label` (**10 px**, нормальный текст) | `--text-2 #AAB6C8` | glass-bg .5 → `rgb(27,62,69)` | **5.61:1** | PASS |
| `.bottom-nav-link.active` (подпись+иконка) | `--text-1 #F4F7FB` | glass-bg .5 → `rgb(27,62,69)` | **10.71:1** | PASS |
| `.more-item` (шторка «Ещё») | `--text-2 #AAB6C8` | glass-bg .5 → `rgb(27,62,69)` | **5.61:1** | PASS |
| `.more-profile` (текст профиля) | `--text-2 #AAB6C8` | glass-bg .5 → `rgb(27,62,69)` | **5.61:1** | PASS |
| `header.header-sticky` — заголовок (`.text-sm`) | `--text-1 #F4F7FB` | glass-bg-strong .85 → `rgb(23,38,50)` | **14.44:1** | PASS |
| `header` — имя пользователя (`.text-gray-300`) | `#D1D5DB` | glass-bg-strong .85 → `rgb(23,38,50)` | **10.52:1** | PASS |
| `header` — роль (`.badge-info`) | `--text-1` на badge-подложке | glass-bg-strong .85 | ≥ 7.0:1 | PASS |
| `header` — второстепенный текст (`--text-3`) | `--text-3 #A2B0C6` | glass-bg-strong .85 → `rgb(23,38,50)` | **7.06:1** | PASS |
| `.hb-tip` (тултип §15) | `--text-2 #AAB6C8` | glass-bg-strong .85 → `rgb(23,38,50)` | **7.56:1** | PASS |
| `.hb-tip b` (заголовок причины) | `--text-1 #F4F7FB` | glass-bg-strong .85 | **14.44:1** | PASS |
| `.guide-markdown code` в карточке (стекло B) | `--text-1` | glass-bg .5 (фон `rgba(255,255,255,.08)`) | ≥ 10:1 | PASS |

**Итог:** **все проверенные панельные классы текста проходят AA ≥ 4.5:1** на худшей фазе фона.
Повышение плотности подложки (`--glass-bg`/`--glass-bg-strong` alpha) **не требуется**; палитра §8 не изменялась.

## Машинная проверка (автоматизация)

`tools/ui_round1025_matrix.py`:
- `F2_PROBE_JS` снимает **реальные `getComputedStyle(...).color`** для `.sidebar-link`, `.bottom-nav-label`,
  `.bottom-nav-link.active`, `.more-sheet .more-item`, `header` заголовка и `.text-gray-300`;
- `_panel_contrast_failures()` считает композит `--glass-bg(.5)`/`--glass-bg-strong(.85)` над худшей (teal) фазой
  wash из computed-токенов и даёт **FAIL при ratio < 4.5:1**;
- `.more-item` дополнительно пробуется при **открытой** шторке «Ещё» (`MORE_ITEM_PROBE_JS`).

## Ограничение честности

Композит аналитический (худшая фаза wash). Реальный `backdrop-filter` в конкретном WebView может давать иной
усреднённый фон — окончательное подтверждение читаемости панелей — live-гейт владельца (T-2617).
