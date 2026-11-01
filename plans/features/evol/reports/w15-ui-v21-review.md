# Reviewer (compact delta) - ASAP-SUMMARY-COVER-INTEGRITY-01 v2.1 UI P1/P2

Кандидат: 26905a89 (worktree evol/impl), диф по git show, не по грязному дереву.

## Вердикт: PASS по проверенному UI-дифу; открыта одна доказательная позиция (§3.4 runtime).

| Пункт | Статус | Доказательство |
| --- | --- | --- |
| §5 один scoped-тумблер, GLOBAL->global, чат->чат, read-only без chat-scope, наследование+reset, pending/epoch | VERIFIED | живой e2e (мой повтор: ASAP-UI-V21-OK), app.js:16016-16430, index.html:5600-5644 |
| §4 пять вкладок речи, «Мат» отдельно, deep-link из «ИИ» | VERIFIED | e2e: tabs=5, profanity/rules отрисованы, deep-link открыл «Мат» |
| §6 нет «...», одна кнопка ⛶ >=44px, dev-геометрия за флагом, аватар+роль только в шапке, drawer ниже инсетов, единый health-блок с локальной тонировкой | VERIFIED | e2e 1280/390/667 + скриншоты моего прогона, app.css:1520-1560,2889-2912 |
| §7 «Избранное» удалено | VERIFIED | тест контракта + grep (0 маркеров) |
| §2 / §3.4 дата активации, gap, серверный таймер, терминальные состояния, stale preview | code VERIFIED / runtime UNVERIFIED | app.js:15954,17900-18000,18138-18200; index.html:3022-3031,3559; живой e2e этого прогона Test Style обложки не открывает |

Проверено: pytest tests/test_webapp_asap_cover_ui_v21.py (27 passed), tools/ui_asap_cover_ui_v21_e2e.py (OK, 1280/390/667), node tests/js/round1020_ui_test.js (JS-UNIT-OK).

## Неблокирующие замечания
1. 390/667: бейдж роли обрезан до «g...» (полное значение только в title).
2. Нет визуального снимка GLOBAL-состояния каталога (числовой probe есть); v21-1280-ai-hub показывает экран речи после deep-link.
3. В чатовой области read-only карточки дважды пишут «управляется глобально».
4. Пустая декоративная полоса стекла над health-блоком только при liquidGlassLib=ON (стенд; прод-default OFF).
