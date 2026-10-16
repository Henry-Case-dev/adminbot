# V63-TAILS — закрытие двух хвостов SOUL-13 (report)

Лейн: V63-TAILS · дата 2026-10-16 · tree: HEAD `9e63b3cf` + незакоммиченные правки бандла
(коммитов/deploy нет). Evidence: `plans/features/asap8-v6-3-live-correction/evidence/v63-tails/`.
Правки по ревью `review-tails.md` (F1–F3/F5) внёс лейн FIX-TAILS-EV — см. раздел в конце.

## TAIL 1 — публичная доступность glass-teststand (SOUL-13.2 / v6.3 §14, REV-W2-N3)

**До (воспроизведено):** анонимный GET через реальный `create_app` (TestClient, монты
`web/app.py:338,344-347`) — `/static/glass-teststand.html` → **200** (19551 B),
`/web/static/glass-teststand.html` → **200**; css/js стенда — 200. Пруф:
`teststand-anon-before.json`.

**Фикс (минимальный, структурный):** страница и её ассеты вынесены ИЗ публично смонтированных
деревьев (никакого кода в `web/app.py` не менялось — монты не тронуты):
- `web/static/glass-teststand.{html,css,js}` → `tests/glass-teststand/` (test-fixture);
- ссылки страницы перенацелены на относительные пути `../../web/static/...` (боевой `app.css`,
  `glass-probe.js` остаются на месте);
- в fixture-CSS добавлен test-env алиас субсета Material Symbols (в голой статик-среде нет
  серверного `/static`-роута и подстановки `__APP_VERSION__`; дубль семейства каскад
  `@font-face` в Chromium не переопределяет — проверено);
- polygon background / runtime liquid glass / glass CSS токены / прочие static — не тронуты
  (`git status` по ним пуст; `web/app.py` без изменений).

**После (реальные коды):** все 7 анонимных путей страницы/ассетов → **404**
(и `/static`, и `/web/static`); боевые ассеты того же контура (`glass-probe.js`, `glass.js`,
`app.css`, `vendor/lg-lens-map.png`, `/web/`, `/healthz`) → 200. Пруф:
`teststand-anon-after.json`.

**Разрешённая test-среда (положительная проверка):** статик-сервер от корня репозитория
(`python -m http.server 8098 --directory <repo>`) → страница 200 + все 4 ссылки (app.css,
css/js стенда, glass-probe.js) 200 с корректными Content-Type — `teststand-test-env-after.json`.
Рендер-проверка двумя инструментами: Playwright (probe: `tierA=true reason=probe-chromium
engine=chromium svg=true backdrop=true`; шрифт из `web/static/fonts` грузится 200; в консоли
только стандартный favicon-404 голой статик-среды) и Browser Use (real rendered) —
скриншоты `teststand-test-env-fullpage.png`, `teststand-test-env-render.png`; панели
hero/soft/solid, сетка-фон, mini-lens рендерятся.

**Тесты (обновлены/добавлены, интент сохранён):**
- `tests/js/glass_probe_test.js` — fixture проверяется на новом месте + гард «страница НЕ в
  публичном static»;
- `tests/test_unified_image_request_round1026.py`, `tests/test_tool_coordinator_round1026.py` —
  `web/static/glass-teststand.*` УДАЛЕНЫ из allowlist диффа: возврат страницы в `web/` валит тест;
- НОВЫЙ `tests/test_webapp_teststand_guard.py` (CONTRACT SOUL-13.2 / REGRESSION REV-W2-N3):
  анонимные 401/403/404 по 7 путям, боевые ассеты 200, скан дерева `web/`, `glass-teststand`
  не упоминается в `web/index.html|app.js|static/app.css`, fixture самодостаточен (локальные
  ссылки резолвятся, нет абсолютных `/static/`).
- **Фальсификация гарда:** временный возврат `web/static/glass-teststand.html` → node-тест
  FAIL, pytest-гард FAIL (2 теста: анонимный 200 + скан дерева); после удаления — снова зелёные.

## TAIL 2 — 6 предсуществующих падений pytest (SOUL-13.6)

Сравнение на одном дереве, одни и те же 6 node id, два интерпретатора (полная матрица —
`tail2-pytest-matrix.json`):

| Тест | Root cause (одна строка) | Класс | Действие | Результат |
|---|---|---|---|---|
| outgoing_guard: html_mode | aiogram 3.29.1 не имеет `InputRichMessageMedia` (пин `aiogram>=3.31.0`) | env (интерпретатор) | — | venv PASS / py‑3 FAIL |
| outgoing_guard: markdown_cover | то же | env | — | venv PASS / py‑3 FAIL |
| summary_publish: level2_publishes | `_rich_media_supported()` = False на aiogram<3.30 → `_deliver_l2_plain`, rich не вызван | env | — | venv PASS / py‑3 FAIL |
| summary_failsoft: l2_called | то же (rich-awaited 0) | env | — | venv PASS / py‑3 FAIL |
| mca02 safe_fetch | был: без trafilatura guard в `_extract_trafilatura` не достигался → облачные фолбеки; закрыт `9e63b3cf` (SOUL-13/SSRF-guard: гард читается первым) | закрытый дефект (порядок гарда) + дефект formation-слоя (F2) | — | venv PASS / py‑3 PASS (после `9e63b3cf`) |
| mca16 experience | stale pin: v6.3 B02 (`1e24eca4`, review-w1 APPROVED) — семантический extractor с ОДНИМ bounded LLM-вызовом на батч | (b) re-pin | пин переписан точно и строже | venv PASS / py‑3 PASS |

Итог (перемер на текущем дереве, см. FIX-TAILS-EV ниже): venv-прогон 6 node id →
**6 passed in 3.26s**; `py -3` → **4 failed, 2 passed** — падают ровно 4 строки aiogram
(`outgoing_guard`: обе, `summary_publish`, `summary_failsoft`) из-за aiogram 3.29.1 против
пина `>=3.31.0` (интерпретаторный артефакт, не дефект продукта); `mca02` зелёный после
`9e63b3cf`, `mca16` — после re-pin (оба env-независимы). На `py -3` ещё нет `pytest-timeout`
(варнинги `Unknown config option: timeout`/`timeout_method` — `--timeout=90` там не работает).
Канон — `.venv\Scripts\python.exe` (aiogram 3.31.0, trafilatura 2.2.0, lxml_html_clean 0.4.5),
как в `requirements.txt`.

## Incidental finding (не чинил — вне write-scope лейна)

`services/web_content_extractor.py:147-151`: проверка `mca_gates.safe_fetch_enabled()` стоит
ПОСЛЕ проверки наличия trafilatura, поэтому SSRF-инвариант «опасное назначение не уходит в
облачные фолбеки» держится только когда trafilatura импортируется. В канонической среде он
держится (trafilatura в requirements), но при сборке/окружении без trafilatura guard
пропускается до фолбеков. Рекомендация Архитектору/Builder: перенести guard-ветку до проверки
провайдера уровня-1 (правка в `services/**` вне этого лейна).

## Команды и результат

- `node tests/js/glass_probe_test.js` → `JS-UNIT-OK glass-probe` (exit 0).
- `.venv\Scripts\python.exe -m pytest tests/test_unified_image_request_round1026.py
  tests/test_tool_coordinator_round1026.py tests/test_webapp_teststand_guard.py
  tests/test_mca16_experience_block_d_round1039.py -q` → **108 passed**.
- 6 node id (venv) → 6 passed in 3.26s; 6 node id (`py -3`) → 4 failed, 2 passed (перемер FIX-TAILS-EV, см. ниже).
- Probe-скрипты лейна: `OPENCODE_WORKFLOW_SCRATCH/v63-tails/` (disposable).

## FIX-SSRF — гард safe-fetch больше не зависит от trafilatura (лейн FIX-SSRF, SOUL-13/SSRF-guard)

Incidental-находка выше закрыта отдельным лейном (без деплоя/коммита).

- **Порядок.** Было (`services/web_content_extractor.py:147-150`): `if trafilatura is None: raise
  RuntimeError` → и только потом `if mca_gates.safe_fetch_enabled()` (SafeFetcher). Стало (строки
  153-162): `safe_fetch_on = mca_gates.safe_fetch_enabled()` читается первым, и при отсутствии
  пакета выполняется `await safe_fetch.aguarded_target(target_url, trusted=False)` (pre-flight
  назначения: normalize/credentials/SSRF-адреса, без загрузки страницы) ДО
  `raise RuntimeError`. Ветка `if safe_fetch_on:` для канонического пути не изменена (ни лишнего
  резолва, ни лишнего запроса); OFF (`MCA_SAFE_FETCH_ENABLED=False`) остаётся точным
  legacy-паритетом. Diff: +15/−3.
- **Тест.** Новый `tests/test_soul13_ssrf_guard_order.py`
  (`TEST-LIFECYCLE: REGRESSION owner=SOUL-13/SSRF-guard`): наличие пакета переключается швом
  модуля (`trafilatura = None`), пакеты не удаляются; опасные литералы (private IP / metadata
  endpoint / `file:` / credentials) не должны доходить до Tavily/Exa в обоих режимах, плюс
  seam-тест «гард прочитан до отказа уровня-1» и OFF-паритет.
- **Фальсификация.** Возврат старого порядка → `5 failed, 5 passed` (краснеют все 4 строки
  «пакета нет + опасный URL» и seam-тест); после восстановления фикса — `10 passed`.
  Существующий `test_mca02…::test_web_extractor_blocks_destination_without_fallback` на старом
  порядке: `.venv` (trafilatura 2.2.0) → **passed** (баг маскирован), `py -3` (импорт
  trafilatura падает → None) → **failed**; на новом порядке `py -3` → **11 passed**.
- **Focused (venv).** Новый файл + `test_web_content_extractor.py` + `test_mca02_safe_fetch_round1027.py`
  + `test_tool_chains_round1026.py::TestFetchArticle/TestR17AndBoundaries` + `test_web_summarizer_service.py`
  + `test_web_handlers.py` + `test_mca11_tool_result_round1028.py` → **189 passed**.
- **Evidence:** `evidence/v63-tails/_ssrf_guard-order.md`, `_ssrf_pytest_matrix.json`
  (sha256 модуля `d4ddcd0b…`, теста `23f182ad…`). Остаточное (не чинил, вне задачи):
  `resolve_failed` не входит в `_POLICY_BLOCK_CODES` — локально неразрешимый URL по-прежнему
  уходит в облако без валидации назначения (pre-existing, решение — за Архитектором).

## FIX-TAILS-EV — закрытие findings ревью (F1–F3, F5), правки evidence/docs

Лейн FIX-TAILS-EV · 2026-10-16 · тот же tree (HEAD `9e63b3cf` + бандл). Код/тесты хвостов
не менялись (ревью их пропустило) — только `requirements.txt` (одна зависимость + комментарий),
матрица, этот отчёт и evidence. Коммитов/deploy нет.

**F1 — матрица пересобрана на текущем дереве** (`evidence/v63-tails/tail2-pytest-matrix.json`):

| Интерпретатор | aiogram | Результат 6 node id |
|---|---|---|
| `.venv\Scripts\python.exe` | 3.31.0 | **6 passed in 3.26s** |
| `py -3` | 3.29.1 | **4 failed, 2 passed** |

4 падения на `py -3` — ровно строки aiogram (`outgoing_guard` ×2, `summary_publish`,
`summary_failsoft`): интерпретаторный артефакт против пина `aiogram>=3.31.0`, не дефект
продукта. `mca02` зелёный на обоих (закрыт `9e63b3cf`), `mca16` — на обоих (re-pin).
Прежние «5 failed, 1 passed» и строка про `mca02` в матрице относились к HEAD `d9b7f389`
и были устаревшими (F1 ревью). Уточнение к `py -3`: там стоит `trafilatura 2.0.0`, но она
**не импортируется** (тот же дефект F2), а `pytest-timeout` отсутствует — `--timeout=90`
из `pytest.ini` в этом интерпретаторе не действует.

**F2/F5 — дефект formation-слоя закрыт в `requirements.txt`.** Добавлена явная строка
`lxml_html_clean>=0.4.1` с комментарием. Причина: jusText 3.0.2 требует
`lxml[html_clean]>=4.4.2`, но extra `html_clean` совпадает с extra `html-clean` из метаданных
lxml 6.x только на pip с PEP 685-нормализацией; на pip 23.2.1 (тот, что CPython 3.12.0 отдаёт
вместе с `venv`) пакет не ставится → `import trafilatura` падает
(`ImportError: lxml.html.clean module is now a separate project lxml_html_clean`), и уровень-1
web-экстрактора в таком окружении выключен. Воспроизведено здесь на `py -3` (первый конфиг
с дефектом) и изоляцией «разница только в этом пакете» в `.venv`: `MASKED → FAIL`, `PRESENT →
OK 2.2.0`; детали и таблица маркеров — `evidence/v63-tails/_lxml_html_clean-packaging.md`.
Полный fresh-venv install не гонялся (сеть/время), референс — наблюдение ревьюера.

**F3 — метки требований.** Исправлено на SOUL-13.2 (стенд) и SOUL-13.6 (6 падений pytest)
в этом отчёте и в матрице; сверено не по ревью, а по источнику:
`plans/features/soul-1/source-current-task.md` — строка 185 (`Стенд /web/static/glass-teststand.html`,
sha256 текста строки `e9a5a0a9…` = `source_text_sha256` SOUL-13.2 в requirements-map),
строка 189 (`6 failed pytest`, sha256 `265284ab…` = SOUL-13.6), строка 183 = SOUL-13.1
(release baseline, другое требование), строка 188 = SOUL-13.5 (git-evidence). Остаточное:
те же метки в 7 файлах бандла (`tests/test_webapp_teststand_guard.py:1,16`,
`tests/js/glass_probe_test.js:110`, `tests/glass-teststand/glass-teststand.html:8`,
`tests/glass-teststand/glass-teststand.css:3`, `tests/test_tool_coordinator_round1026.py:762`,
`tests/test_unified_image_request_round1026.py:740`,
`tests/test_mca16_experience_block_d_round1039.py:252`) — это тесты/фикстуры хвостов,
запрещённые этому лейну (`DO_NOT_TOUCH`); правка меток в них не сделана.
Recheck-грепа по бандлу поэтому даст 7 файлов тестов + **литеральные** `SOUL-13.1`/`SOUL-13.5`
в двух строках выше: это ссылки на СОСЕДНИЕ требования (объяснение, почему метки были
неверны), а не метки этого бандла.

**Гарды после правок (ничего в коде бандла не тронуто):**
`node tests/js/glass_probe_test.js` → `JS-UNIT-OK glass-probe` (exit 0);
`.venv pytest tests/test_webapp_teststand_guard.py -q` → `5 passed, 1 warning in 3.40s`.

**Отпечаток (sha256[:16]):** guard `379d53d7`, node-тест `bffc3a50`, fixture html `2c209916` /
css `468ffb92` / js `f8739e29`, mca16-тест `86276461`, `services/web_content_extractor.py`
`d4ddcd0b`, `requirements.txt` `15157fb4` (после правки). Метки/матрицу ревьюер вяжет заново
по изменённым файлам.
**FIX-LABELS (2026-10-16, comments-only):** остаточные метки из абзаца F3 выше исправлены
(стенд 13.1→13.2, pytest-пин mca16 13.5→13.6); хеши guard/node/html/css/mca16 выше обновлены
по факту. Таблица old→new и причины — `review-tails.md`, раздел «Post-review comment corrections
(FIX-LABELS)»; фикстура js, `web_content_extractor.py` и `requirements.txt` в этот заход не менялись.
