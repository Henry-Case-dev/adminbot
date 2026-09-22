# round1025 HOTFIX8 — отчёт UI-матрицы (T-2774, UPD2 §8.5/§9)

**Дата:** 2026-09-22 · **Инструмент:** `tools/ui_round1025_matrix.py` (Playwright/Chromium, `web/index.html` + stubbed `/api`).
**Запуск:** `.venv\Scripts\python.exe tools/ui_round1025_matrix.py` → **failures: 0**.
**Артефакты:** `tools/_ui_round1025_raw.json`, `tools/_ui_round1025_shots/*.png` (40 скриншотов).

## 5 обязательных режимов

| Режим | Вьюпорты | Результат |
|---|---|---|
| Desktop normal | 1280×800, 1440×900, 1920×1080, 2560×1440 | PASS (0 fail) |
| Desktop fullscreen | те же, `fullscreen-mode` | PASS (0 fail) |
| Tablet | 768×1024, 1024×768 | PASS (0 fail) |
| Mobile portrait | 320×700, 360×780, 390×844, 430×932 | PASS (0 fail) |
| Mobile fullscreen inside Telegram WebView | mobile-вьюпорты + TMA-стаб (`fullscreenChanged`/viewport offset) | **эмуляция PASS**; реальный WebView — live-гейт **T-2776** (владелец) |

## Проверенные инварианты (§6)

- Shell ≠ карточка: computed shell bg `rgba(24,28,38,.72)` (mobile `.78`) vs card `rgba(21,27,42,.5)`.
- Нет цветной линзы на shell: `shellA=False`; `data-glass="shell"` у sidebar/header/drawer/bottom-nav/more-sheet.
- Стекло §4: `blur(18px) saturate(115%)`.
- Aurora живой: 5 blob-слоёв, `animation-name = aurora-blob-1` (не static); `lg-bg-paused` → paused; reduced-motion → `animation: none`.
- Геометрия: sidebar 216px (∈208–224); gap header↔первый блок 16px (∈16–20); `scrollWidth ≤ innerWidth+1` везде.
- Bottom-nav/more-sheet: `rect.bottom ≤ innerHeight+1` (и `stableHeight` при симуляции бара); hit-area ≥44×44.
- F2-чекер усилен: фон «static» (нет активной анимации) → FAIL.

## Ограничение

Реальный Telegram WebView (fullscreen, `safeAreaInset`/`contentSafeAreaInset`, нативные кнопки, FPS blob/преломления) headless не воспроизводится — обязательный live-гейт владельца **T-2776**.
