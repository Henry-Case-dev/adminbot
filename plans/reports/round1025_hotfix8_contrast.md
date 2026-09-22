# round1025 HOTFIX8 — AA-контраст shell v3 / aurora (T-2766, ADR-1025-16 D2)

**Дата:** 2026-09-22 · **Фича:** `hotfix8-shell-glass-aurora-round1025` · **Задачи:** T-2759, T-2760, T-2766.

## Метод

- **Композит (консервативно, без blur):** эффективный фон shell = `--shell-bg`
  (desktop `rgba(24,28,38,.72)`; mobile ≤767 `rgba(24,28,38,.78)`) поверх
  **худшей (самой светлой) фазы aurora** — teal-blob `rgba(66,214,196,.60)` при
  opacity слоя `.5` (итоговая alpha `.30`) над `--surface-0 #090D17`.
  Blur 18px в AA-расчёт не добавляется (консервативно: размытие усредняет фон,
  но не гарантирует затемнение; берём худший пик).
- **Текст:** фактические токены потребителей (`.sidebar-link` → `--text-2`
  `#AAB6C8`, активные/заголовок → `--text-1 #F4F7FB`, `.text-gray-500` →
  `--text-3 #A2B0C6`).
- **Порог:** WCAG AA ≥ **4.5:1** для мелкого текста (12–13 px, нормальный вес).
- Расчёт: `tools/ui_round1025_matrix.py` — те же `_lum_rgb`/`_contrast_rgb`.

## Результат (худшая фаза aurora = teal)

| Класс | Текст | Эффективный фон (composite) | Ratio | AA |
|---|---|---|--:|:--:|
| `.sidebar-link` | `--text-2` #AAB6C8 | shell .72 над teal-aurora | **7.33:1** | PASS |
| `.sidebar-link.active` | `--text-1` #F4F7FB | shell .72 над teal-aurora | **14.00:1** | PASS |
| `.bottom-nav-label` | `--text-2` #AAB6C8 | shell .78 (mobile) над teal-aurora | **7.55:1** | PASS |
| `.bottom-nav-link.active` | `--text-1` #F4F7FB | shell .78 (mobile) над teal-aurora | **14.41:1** | PASS |
| `.more-item` | `--text-2` #AAB6C8 | shell .78 (mobile) над teal-aurora | **7.55:1** | PASS |
| `header` (`.header-title-wrap .text-sm`) | `--text-1` #F4F7FB | shell .72 над teal-aurora | **14.00:1** | PASS |
| `.scope-trigger` (`.field`) | `--text-1` #F4F7FB | field `rgba(255,255,255,.06)` над shell .72 | **11.70:1** | PASS |

Все пары ≥ **4.5:1** (минимум 7.33:1) — shell v3 не ухудшает AA; shell — тёмно-
серый/графитовый слой, читаемость меню/шапки сохранена. Aurora не создаёт ореол
вокруг shell (фон — отдельный задний слой, `z-index:0` < `#app`) и не «просвечивает»
сквозь карточки неуместно (карточный `--glass-bg` alpha `.5` не менялся).
