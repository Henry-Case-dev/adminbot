# W4 — регрессионные прогоны (точные команды и результат)

Дата: 2026-10-23. Python: `C:\Code\Python\adminbot\.venv\Scripts\python.exe`.
Node: `node` (проектный). CWD — корень репозитория.
Кандидат — рабочее дерево после правок W4 (файлы: `web/app.js`,
`web/index.html`, `web/static/app.css`, `web/static/glass-refraction.js`,
`tools/ui_w4_ui_e2e.py`).

## Зелёные (PASS)

| Команда | Результат |
|---|---|
| `node tests/js/glass_refraction_test.js` | `JS-UNIT-OK glass-refraction` |
| `node tests/js/glass_probe_test.js` | `JS-UNIT-OK glass-probe` |
| `node tests/js/round1025_hotfix10_glass_geometry_bg_test.js` | `HOTFIX10-GLASS-GEOMETRY-BG-OK` |
| `.venv/Scripts/python.exe tools/ui_win_glass_refraction_e2e.py` | `WG-REFRACT-E2E-OK` (A 21, C 4, B 10, D 2 проверки; paintMs<6ms, p95<40ms) |
| `.venv/Scripts/python.exe tools/ui_asap8_w2_shell_e2e.py` | `W2-SHELL-E2E-OK` (нет failed_checks, header 116/116/113/109, nav 4 сегмента, scrollWidth=vw) |
| `.venv/Scripts/python.exe tests/ui_p0a_ux_speech_compact_e2e.py` | `ИТОГ: failures=0, POST=22` (savebar-контракт §5.5 сохранён) |
| `.venv/Scripts/python.exe tools/ui_w4_ui_e2e.py` | `ИТОГ: failures=0, POST=8, notes=159` (новый e2e слайса) |
| `.venv/Scripts/python.exe -m pytest tests/test_soul1_w6_speech_ui.py tests/test_webapp_design_tokens_round1025.py tests/test_webapp_nav_disclosure_ui.py tests/test_webapp_js_unit.py tests/test_ui_verbilizer_tabs_round1023.py tests/test_webapp_parity_smoke.py tests/test_web_prompts.py -q` | `171 passed` |

## Красное ДО и ПОСЛЕ (pre-existing, не связано с W4)

`.venv/Scripts/python.exe tools/ui_soul1_w6_speech_e2e.py --no-shots`
→ `failures=2`:
`390: предпросмотр выражения не обновился`, `1440: …`.

Причина: фикстура `plans/features/soul-1/evidence/w6/api-fixture.json` отдаёт
контрол «Остроумие» уже со значением `high`, а тест выбирает `high` →
`select_option` не меняет черновик, и предпросмотр остаётся «слой выражения
пуст». Проверено дважды на **чистом master** (`git stash push -- web/`):
поведение идентично (`BEFORE`/`AFTER` предпросмотра равны), т.е. дефект
теста/фикстуры, а не кандидата W4. Функционально слой выражения проверяется
зелёным `tests/ui_p0a_ux_speech_compact_e2e.py` и разделом «Выражение» в
`tools/ui_w4_ui_e2e.py`.

## Что не гонялось

- Полный `pytest` всего репозитория: не запускался (blast radius W4 ограничен
  `web/**`; затронутые контракты покрыты списком выше). Это ограничение
  зафиксировано, а не «закрыто» зелёным прогоном.
- Реальный Telegram WebView / физический Android: стенд — Chromium.
