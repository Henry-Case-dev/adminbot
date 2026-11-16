# P0-PROD-DISK-01 — пороги диска на «Статусе» (UI)

Инкремент: видимая классификация СУЩЕСТВУЮЩЕЙ телеметрии
`/api/status.server.disk` (`percent` либо `used`/`total`). Новый мониторинг,
второй `/api/status`, правки `services/status_service.py` и повышение
существующих порогов — НЕ добавлялись.

База: `bca18c1e` (deployed). Ветка: `fix/p0-disk-status-thresholds`.
Статус: кандидат на независимое ревью — **не деплой, не VERIFIED**.

## Контракт

| Заполнение | Уровень | Полоса | Текст (не только цвет) |
|---|---|---|---|
| `>= 90 %` | `crit` | существующий `bar-red` (красная) | «Критично: диск заполнен на N% — освободите место» |
| `>= 85 %` | `warn` | янтарная (`--warn`) | «Внимание: диск заполнен на N% — место заканчивается» |
| `< 85 %` | `ok` | обычная (teal) | нет |
| нет данных | `unknown` | штриховка + «нет данных», заливки нет | нет (не ложное «здорово») |

- Пороги — именованные константы `STATUS_DISK_WARN_PERCENT = 85`,
  `STATUS_DISK_CRIT_PERCENT = 90` в `web/app.js`; в ветках классификации
  магических чисел нет.
- Классифицируется та же цифра, что показана пользователю (округлённая
  `_ctlProgressModel`), поэтому текст, порог и цвет не расходятся.
- Доступность: предупреждение — `role="status"`, `aria-live="polite"`,
  `aria-atomic="true"` + текст; `aria-label` прогрессбара называет проблему.
- Соседние блоки «Статуса» (CPU/RAM, heartbeat, бюджеты, сегмент «Сервер»)
  не изменены; добавлена одна строка предупреждения под полосой диска.

## Изменения

- `web/app.js`: константы порогов; computed `ctlDiskAlert`
  (`ok/warn/crit/unknown`, текст, aria-текст). `ctlDiskProg` не изменён.
- `web/index.html`: блок диска обёрнут в `.status-disk` с
  `data-disk-level`; `bar-red` на заливке при `crit`; строка предупреждения.
- `web/static/app.css`: стили уровня (янтарная/красная заливка, цвет текста)
  рядом с существующей системой `.ctl-progress` (только токены размеров).
- `tests/js/p0_disk_status_thresholds_test.js` (+ регистрация в
  `tests/test_webapp_js_unit.py`).

## Проверки (локально, worktree)

```text
node tests/js/p0_disk_status_thresholds_test.js   → P0-DISK-STATUS-OK
  покрытие: 84 / 85 / 89 / 90 / 95 / нет данных / used+total без percent /
  округление 84.9→85 и 89.6→90 / константы вместо магических чисел /
  разметка + aria-live + bar-red / CPU, RAM и бюджет контекста не переписаны

node tests/js/evol_w11_controls_test.js           → EVOL-W11-CONTROLS-OK
node tests/js/round1025_f11_status_grid_test.js   → F11-STATUS-GRID-OK, F11-HEARTBEAT-OK
node tests/js/asap_ui02_status_ribbons_test.js    → ASAP-UI02-RIBBONS-OK
node tests/js/evol032_health_glass_test.js        → EVOL032-OK
node tests/js/app_methods_dup_keys_guard_test.js  → METHODS-DUP-KEYS-OK
node tests/js/vue_mount_test.js                   → VUE-MOUNT-OK

pytest (worktree, целевой набор): 411 passed — test_webapp_js_unit,
  test_webapp_evol_w11_controls, test_webapp_status_control,
  test_status_service, test_webapp_f11_round1025,
  test_webapp_evol_w10_sections, test_status_section_ui_merge_round1019,
  test_evol032_health_glass, test_webapp_design_tokens_round1025,
  hotfix6–10, test_webapp_evol_w12_internals.
```

Red-baseline (тот же unit на `bca18c1e`, копия в probe-каталоге runs):
`TypeError: Cannot read properties of undefined (reading 'call')` —
`ctlDiskAlert` на базе отсутствует, классификации нет (тест различающий).

Pre-existing, НЕ связаны с изменением (доказано на базе / по diff):
`test_webapp_asap_cover_ui_v21::test_history_shows_activation_date`
(в `bca18c1e:web/app.js` нет `a.created_at` в `activeLabel`);
`test_webapp_ui_rework_round1020` — устаревшие снимки навигации
(`mod_time`, 16 модулей); мой diff не трогает `TABS`/`MODULES`.

## Визуальная проверка (Playwright, локальный harness)

`capture_p0_disk_status_ui.py` — статический сервер
`tools/ui_round1025_matrix.py` + route-стабы `/api/*` + mock Telegram SDK
(НЕ live TMA). 1280×800 и 390×844, сценарии 92 / 86 / 50 / нет данных.

```text
.venv\Scripts\python.exe plans/features/p0-prod-disk-01/evidence/ui/capture_p0_disk_status_ui.py
P0-DISK-UI-OK  (8 сценариев, 0 ошибок)
```

Проверено в браузере: `data-disk-level`, текст и цвет предупреждения,
`role=status`/`aria-live`, `bar-red` (сплошной красный `#ef4444`) при 92 %,
янтарная заливка при 86 %, обычная при 50 %, штриховка и «нет данных» без
предупреждения при отсутствии телеметрии; heartbeat/«Сервер»/CPU/RAM на
месте; горизонтального переполнения нет. Сырые данные — `ui-checks.json`.

Скриншоты (viewport-размеры из имени):

- `status_disk_92_desktop_1280x800.png`, `status_disk_92_mobile_390x844.png`
- `status_disk_86_desktop_1280x800.png`, `status_disk_86_mobile_390x844.png`
- `status_disk_50_desktop_1280x800.png`, `status_disk_50_mobile_390x844.png`
- `status_disk_unknown_desktop_1280x800.png`,
  `status_disk_unknown_mobile_390x844.png`

## Ограничения

- Проверка — на локальном harness с фикстурной телеметрией; production
  effective-state и реальные проценты диска этим изменением не проверяются
  (деплоя нет).
- Независимое ревью ещё не проводилось; VERIFIED не заявляется.
