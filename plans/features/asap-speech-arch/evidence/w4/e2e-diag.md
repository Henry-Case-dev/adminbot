# W4 e2e — диагностика «178 падений» (LANE W4-E2E-DIAG, 25.10.2026)

## Симптом

В `plans/workflow_state.md` осталось: «W4 e2e 178 failures — pre-existing,
разобрать отдельно». Требовалось понять, это устаревший стенд или реальная
регрессия UI в 2.58.118–2.58.125.

## Что выяснено

1. **178 падений — НЕ у `tools/ui_w4_ui_e2e.py`.** На HEAD (2.58.124/125)
   W4-раннер даёт `failures=0, POST=8, notes=163`, а speech-e2e
   `tests/ui_p0a_ux_speech_compact_e2e.py` — `failures=0, POST=22`.
2. Источник 178 — **`tools/ui_round1025_matrix.py`** (широкая shell/glass
   матрица, 10 вьюпортов × маршруты). Воспроизведено на HEAD до правок:
   `[matrix] failures: 178`, exit 1.
3. Состав 178 (ровно, сгруппировано):

   | Кол-во | Проверка | Статус |
   |---|---|---|
   | 76 | `нет bottom-nav (<768)` | устаревшая: bottom-nav удалён в D13 (2.58.77) |
   | 79 | `тач-цель селектора 40px < 44` | устаревшая: U01.2 задаёт 40px |
   | 10 | `ни один [data-glass="a"] не получил tier A` | устаревшая: render-probe честно даёт Tier B |
   | 10 | `--glass-displace=''` | устаревшая: токен удалён в W2-Glass U08.3 |
   | 3 | `SaveBar не в footer.modal-actions` | устаревшая: D13 — footer dirty-only |

4. Корень: матрица последний раз обновлена **23.09.2026 (76fc5e15, 2.58.19)**
   и не была согласована с более поздними ПРИНЯТЫМИ контрактами:
   - **D13 (217c9655, 2.58.77)**: `.bottom-nav`/`.more-sheet` удалены,
     мобильный shell — компактная верхняя строка `.mobile-topnav` (row B,
     ссылки ≥44×44); постоянный SaveBar/footer убран — `<sticky-save>`
     рендерится только в dirty/saving/failed;
   - **U01.2 (c0535280, 2.58.117)**: в компактной шапке
     `.app-shell.shell-mobile .scope-trigger { min-height: 40px }`
     (32px — только landscape ≤500px);
   - **W2-Glass U08.3 (c0535280)**: `--glass-displace`/фейковое `url(#lg-lens)`
     superseded render-probe'ом (`glass-probe.js`); до подтверждения — честный
     Tier B с `data-glass-reason="engine-unproven-backdrop-url"`.
5. Не регрессия 2.58.118–2.58.125: `plans/features/cfg/evidence/cfg-04/blast-radius.txt`
   (20.10.2026, база master 7a3c1f92 = 2.58.96) уже фиксирует те же 178
   строк и на master, и на кандидате (diff по множествам 0/0). Матрица красная
   минимум с 2.58.96, фактически — с 2.58.77.

**Классификация: (а) устаревший стенд/проверки.** Код `web/**` не менялся;
регрессии UI нет. W4-поверхность и speech-e2e зелёные и до, и после.

## Что исправлено (только стенд)

`tools/ui_round1025_matrix.py` — проверки приведены к действующему контракту,
ни одна не ослаблена:

1. `<768`: вместо требования bottom-nav — **утверждается его отсутствие**
   + видимая `.mobile-topnav` + тач-цель её ссылок ≥44 (PROBE_JS расширен
   полями `mobileTopnav/mobileTopnavCount/mobileTopnavMinTouch`).
2. `_scope_failures`: порог scope-trigger 40px (32 для landscape ≤500px),
   позиционная проверка «под заголовком» сохранена.
3. Glass: снята проверка удалённого `--glass-displace`; проверяются tier-маркеры,
   допустимые значения a/b/c, отсутствие `tier=a` с downgraded и наличие
   `engine-unproven-*` причины, если Tier A нет. Tier A без причины — FAIL.
4. H9 module modal: окно сначала переводится в dirty штатными input/change
   (как живой пользователь), затем проверяется `SaveBar` внутри
   `footer.modal-actions`; после проверки состояние сбрасывается, чтобы
   overlay/guard не ломал последующие fullscreen-сцены.

## Проверка (после правок, тот же HEAD-код UI)

| Прогон | До | После |
|---|---|---|
| `tools/ui_round1025_matrix.py` | **178 failures**, exit 1 | **0 failures**, exit 0 |
| `tools/ui_w4_ui_e2e.py --no-shots` | 0 (на HEAD) | **0** |
| `tests/ui_p0a_ux_speech_compact_e2e.py` | 0 (на HEAD) | **0, POST=22** |
| `pytest` профиль (ui_rework_round1020, hotfix7/9/10, nav_disclosure, js_unit) | — | **155 passed** |

Скриншоты/`_ui_round1025_raw.json` — артефакты прогона (gitignored), в коммит
не входят. Прод/SSH не использовались.

## Остаточный риск

- Матрица остаётся инструментом эвристик: новые shell-решения должны
  синхронно обновлять её проверки, иначе снова появятся «исторические» FAIL.
- 40px scope-trigger — принятый компромисс U01.2; если владелец потребует
  строго 44px, менять нужно CSS и порог в матрице вместе (не «подкручивать»
  проверку).
