# review-coverage — REV-COVER (независимая сверка «исходник ↔ карта», барьер перед Wave 1)

- Дата: 15.10.2026. Ревьюер: REV-COVER (read-only leaf, parent-барьер).
- Кандидат: `requirements-map.json` (source_sha256 `d0b4f611ac5eff7d228a1d2a2d1e283f04b26625f2dac89ab5ad1145f10e686d`) + `requirements-map.md`, `source-reconciliation.md`, `baseline-inventory.md`, `waves.md`, `baseline-pytest-b10.md` против снапшота `source-lines-37423-EOF.md` (451 строка, прочитан целиком).
- Метод: reverse comparison по каждой содержательной строке снапшота (включая прозу «Исполнить/DoD/UI contract/Геометрия», код-блоки U07.1/U07.2/U08.2, таблицы B10/U08, V01–V07, FINAL, «пределы»), программные проверки JSON (counts, dispositions, полнота required-полей, дубли ID, пропуски строк), сверка reconciliation и waves.

## 1. Что подтверждено (положительное)

- Счётчики сходятся: **148 inventory + 74 manual = 222; required = 200** (61 manual + 139 inventory), context=13, duplicate=9. Заголовок requirements-map.md корректен.
- У всех 200 required-позиций заполнены req_id + slice + acceptance (программная проверка: 0 пропусков). Дубликатов req_id нет.
- **Ни одной** пометки `user_excluded`/`backlog` — владелец исключений не давал; дубликаты классифицированы с конкретными причинами (заголовки/повторы/файлы-мишени/baseline-наблюдения), не как «мусор».
- Line-by-line: все нумерованные пункты B01.1–6, B02.1–5, B03.1–5 (вкл. B03.4=D06), B04.1–6, B05.1–3 +SYM/DOD, U01.1–5+BASE+TESTS, U02.1–3, U03.1–4, U04.1–2, U05.1–4 (вкл. 7 виджетов D12 поимённо), U06.1–3, U07.0–3 (a–f, 2a–2e, 3a–3c, NOHACKS, NOINJECT, HARD, TMA-контракты, платформы, launch-mode, симптомы Windows/Android), U08.0–5 (MATERIAL/PALETTE/AUDIT/PROBE/LAYERS/PARAMS/3a–3e/4a–4f/5.1–5.5/DOD), B06–B09, B10-R01–R19+PYTEST, B11 SCOPE/CHAIN/E2E, B12.1–6, V01–V07, FINAL.1–4, REQ-REL-SHA, PRIN-*, REQ-0-1…0-4 — имеют owner-slice и наблюдаемый acceptance (числа, тесты, скриншоты, live-метки; «сделать красиво» не обнаружено).
- Reconciliation: все 26 legacy ID (C01–C10, C03A, C06A, D01–D14) покрыты через B10-R01–R19 + §2; волны v6 A/B/C/P1/UI/D14 сведены в §4; ключевые остатки отражены: **B03.4=D06 (`_vec_candidates`, L4206/4423), U05.3=7 виджетов D12, B09=D02-остаток (wa3)**; §5 — таблица остатков f10 → v6.3.
- baseline-inventory: owner-файлы/строки проверены на f58a644; discrepancies честные (recover не вызывает Telegram, CATEGORY_TEMPORAL отсутствует в SEED_CATEGORIES — подтверждено); baseline-pytest-b10 классифицирует 3 failed pytest с прогонами 15.10.2026 (1 реальная регрессия direct_chat_concurrency + 2 green/flaky) — опора для REQ-B10-PYTEST есть.
- waves.md: все P0/P1-требования распределены по W1–W4; V-блокеры сведены в таблицу; W2-конфликт app.css/app.js/index.html разрешён явно: файловое владение по селекторам/функциям + merge-порядок shell → fullscreen → glass + контракт-слот U07-fallback↔row A + B01.4 UI↔W1-L1 API (риски 1–2). Миграции БД — общий реестр.

## 2. Блокеры (3 — все правки карты/waves, не кода)

1. **BLOCKER · снапшот строка 262 (U08.2)** — критерий «Не давать translucent panel перекрывать scroll-container / Telegram native hit zones» отсутствует в acceptance REQ-U08-2 / REQ-U08-2-LAYERS / U08.5.\* (grep по карте: 0 попаданий; native hit-зоны покрыты только для fullscreen-кнопки — U07.2e). Builder, зелёный по карте, может положить стеклянную панель поверх scroll-контейнера/нативной зоны и пройти приёмку. **Фикс (PM, 1 строка):** дополнить acceptance REQ-U08-2 (или U08.5.3): «стеклянные/полупрозрачные слои не перекрывают scroll-container и Telegram native hit-зоны (hit-тест/elementFromPoint)». Recheck: grep карты.
2. **BLOCKER · снапшот строка 309 (U08.2/Tier B)** — критерий «если mask-composite не поддерживается — альтернативный rim по box-shadow/overlay, **без исчезновения controls**» есть только в context-записи M036 со ссылкой «учтено в U08.3a», но в acceptance U08.3a/U08.5.3 его нет (grep «mask-composite» → только M036). Fallback-контракт потерян. **Фикс (PM, 1 строка):** добавить в acceptance U08.5.3: «при неподдерживаемом mask-composite rim по box-shadow/overlay, controls видимы (скриншот fallback-рендера)». Recheck: grep карты.
3. **BLOCKER · waves.md (§0/REQ-0-1)** — REQ-0-1 (health/gates/БД/настройки чата/24–48h данные, сверка «26/26») и /healthz-сверка REQ-0-BASESHA — P0 «Обязательный старт», но Wave 0 закрыт как «сделано», REQ-0-1 = PENDING, а baseline-inventory §3 откладывает сбор «на S0» **без назначенного лейна** (W1–W4 его не содержат; W4-L2 ведёт только B12/B10/FINAL/REQ-REL-SHA). P0-требование де-факто осиротело в волновом плане. **Фикс (PM, 1 строка в waves.md):** назначить владельца — read-only сбор S0-данных до первого деплоя (пре-барьер Wave 1 или отдельный шаг W1 join barrier). Recheck: waves.md содержит строку назначения.

## 3. Nonblocking

- M007 evidence: «148 inventory + 65 manual» — устаревшее число (фактически 74 manual; итог 222 верен в шапке md и waves). Обновить заодно с фиксом блокеров.

## 4. Вердикт

**Needs Fixes** — карта покрывает ТЗ по существу на ~99% (сильная детализация, honest live-метки, корректные reconciliation/waves), но барьер требует устранить 3 пропуска: два потерянных критерия U08 (строки 262, 309 снапшота) и осиротевший S0-сбор REQ-0-1 в waves.md. Все фиксы — точечные правки PM (3 строки суммарно), кода не касаются; после них карта готова к старту Wave 1.
