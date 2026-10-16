# REV-TAILS — независимое ревью двух хвостов v6.3 (план SOUL-13.2 / SOUL-13.6)

Reviewer: REV-TAILS (read-only; код не правился). 2026-10-16.
**Verdict: Needs Fixes** — только правки evidence-артефактов (F1–F3/F5); код и тесты
tail-1 и re-pin mca16 прошли независимую проверку и правок не требуют.
Роль-разрешение: де-публикация — predeploy-часть SOUL-13.2; live-проба анонимного
доступа на проде остаётся postdeploy-гейтом (DevOps), статус «approved for controlled
deployment, parent not DONE».

## Привязка кандидата
- HEAD `9e63b3cf2a77807fbb84afe324701867eb682101` + незакоммиченный бандл; worktree
  НЕ заморожен: во время ревью параллельный лейн (HOTFIX-TIERA, SOUL-1) изменил
  `web/app.js` — в бандл не входит и не должен попасть в его коммит.
- Хеши (sha256[:16]): guard=d35f17c5, node-тест=c8e71eda, html=6628fb5a, css=b3e9b2b7,
  js=f8739e29 (== HEAD `web/static/glass-teststand.js`, байт-в-байт переезд),
  mca16-тест=1adce018, matrix=7da3bcc9, report=e156478a.
  Удалено из HEAD: html a4dd174a / css 4d4c08e9 / js f8739e29.
- Не тронуто (git clean + хеши): `web/static/polygon-background.js` 157874df,
  `glass-probe.js` 64a5f744, `glass.js` 3f95b925, `app.css` c28d4c89; `web/app.py`
  в diff отсутствует (0 правок).

## Ledger (измерено лично, не по отчёту лейна)
| # | Пункт | Статус | Доказательство |
|---|---|---|---|
| 1 | Анонимные 7 путей стенда → 404 (оба монта) | VERIFIED | TestClient(create_app): /static/{html,css,js}, /web/static/{html,css,js}, /web/glass-teststand.html → 404; c `?v=stand` → 404; HEAD → 404 |
| 2 | Боевые ассеты живы | VERIFIED | /static/glass-probe.js, glass.js, app.css, vendor/lg-lens-map.png, fonts/material-symbols-rounded.woff2, /web/, /web/index.html, /healthz → 200 |
| 3 | Стенд работает в разрешённой test-среде | VERIFIED | `python -m http.server 8098 --directory <repo>`: страница + все 5 ссылок 200; probe `tierA=true reason=probe-chromium svg=true backdrop=true`; `.msr` = Material Symbols Rounded Stand; консоль — только favicon-404; Playwright и Browser Use (независимо) отрендерили сетку/волну/hero-линзу с рефракцией |
| 4 | Гард фальсифицирован (scratch-копия, реальный worktree не тронут) | VERIFIED | возврат страницы в `web/static/` → node FAIL («стенд НЕ в публичном static»), pytest 2 failed (anonymous 200 + скан дерева); после удаления → node OK, pytest 5 passed |
| 5 | Allow-list-тесты стали строже | VERIFIED | из `tests/test_tool_coordinator_round1026.py:759-772` и `tests/test_unified_image_request_round1026.py:737-748` удалены 3 записи `web/static/glass-teststand.*`; skip/xfail не добавлялись; возврат файла валит оба теста |
| 6 | Дифф переезда минимален | VERIFIED | JS байт-в-байт; HTML: комментарий + 4 ссылки → относительные; CSS: +@font-face test-env-алиас и `.msr`-переназначение (остальное байт-в-байт) |
| 7 | Канонический venv: 6 node id | VERIFIED | `.venv`: 6 passed in 3.01s |
| 8 | `py -3` на текущем HEAD | VERIFIED (матрица устарела) | 4 failed / 2 passed: падают 4 aiogram-теста (3.29.1 < пина 3.31.0), mca02 и mca16 — зелёные (mca02 закрыт коммитом 9e63b3cf) |
| 9 | Re-pin mca16 соответствует одобренному B02 | VERIFIED | review-w1.md: B02 APPROVED (батч ≤4×≤10, ОДИН LLM-вызов); тест пиннит count(generate())==1, вызов внутри `_semantic_llm_batch`, step="semantic_extract", max_output_tokens=SEMANTIC_BATCH_MAX_TOKENS, llm default None; зелёный на обоих интерпретаторах |
| 10 | SOUL-13.2 live-часть (анонимная проба на проде) | READY_FOR_LIVE | возможно только postdeploy; канарейка описана в отчёте (анонимный GET на боевой хост) |

## Findings
**F1 (Medium, evidence-accuracy) — устаревшая матрица `py -3`.**
`evidence/v63-tails/tail2-pytest-matrix.json:19` («5 failed, 1 passed») и
`v63-tails-report.md:64-65` противоречат текущему HEAD (измерено: 4 failed / 2 passed,
mca02 зелёный после 9e63b3cf). Строка 54/57 и «action: none» для mca02 тоже устарели.
Минимум: пересобрать матрицу на HEAD (venv 6/6; py-3 4/2, перечислить именно 4 aiogram-строки).

**F2 (Medium, классификация) — mca02 не только «interpreter».**
`tail2-pytest-matrix.json:57` + `v63-tails-report.md:61,66`: `pip install -r requirements.txt`
НЕ даёт импортируемую trafilatura: jusText 3.0.2 требует `lxml[html_clean]>=4.4.2`, а lxml 6.x
это extra не предоставляет (lxml_html_clean ставился в venv вручную: Required-by пуст).
Воспроизведено в чистом venv 2026-10-16: trafilatura 2.3.1 / lxml 6.1.3 / jusText 3.0.2 →
`ImportError: lxml.html.clean ... lxml_html_clean`. На 6 тестов сейчас не влияет (после
9e63b3cf mca02 зелёный даже без trafilatura), но канонический env из requirements.txt
не воспроизводим, и в таком env основной путь web-экстрактора выключен.
Минимум: классифицировать как дефект formation-слоя, добавить `lxml_html_clean` в
`requirements.txt` (одна строка) либо зафиксировать follow-up с владельцем.

**F3 (Low, bookkeeping) — неверные req_id.** Бандл маркирован SOUL-13.1/13.5, а по
requirements-map стенд = SOUL-13.2 (live postdeploy), 6 падений = SOUL-13.6:
`v63-tails-report.md:6,43,50`; `tests/test_webapp_teststand_guard.py:1,16`;
`tests/js/glass_probe_test.js:110`; `tests/glass-teststand/glass-teststand.html:8`;
`tests/glass-teststand/glass-teststand.css:3`;
`tests/test_tool_coordinator_round1026.py:762`; `tests/test_unified_image_request_round1026.py:740`;
`tests/test_mca16_experience_block_d_round1039.py:252`. Минимум: заменить 13.1→13.2, 13.5→13.6.

**F4 (Info) — коммитить бандл выборочно.** В worktree параллельно меняются `web/app.js`
(HOTFIX-TIERA), `services/direct_chat_service.py`, `disk_retention.py`, `param_catalog.py`,
`prompt_migrations.py`, `prompt_style_blocks.py`, новые `services/prompt_*.py`, `tests/test_soul1_*` —
это чужие лейны; в коммит хвостов не включать (иначе деплой потащит незаревьюенное).

**F5 (Info/backlog, pre-existing) — `lxml_html_clean` в requirements.txt** (см. F2):
влияние на прод не проверялось (SSH запрещён); если прод-venv тоже без него — web-экстрактор
молча ходит в облачные фолбеки. Решение за Архитектором/PM.

## Единственный production-эффект бандла
Удаление `web/static/glass-teststand.{html,css,js}` из публично смонтированного дерева —
ровно требуемый (страница/ассеты анониму 404). Иных production-изменений в бандле нет:
остальное — тесты/fixture/отчёт. (`services/web_content_extractor.py` из HEAD 9e63b3cf —
отдельный, уже закоммиченный лейн, вне этого бандла.)

## Recheck после правок
1) F1: повторный прогон 6 node id на обоих интерпретаторах (ожидание: venv 6/6; py-3 4/2).
2) F3: `rg "SOUL-13\.[15]"` по файлам бандла → пусто.
3) F2/F5: решение по `requirements.txt` зафиксировано (патч или follow-up с владельцем).
4) Перед деплоем: `node tests/js/glass_probe_test.js`; guard + 2 allow-list + mca16 (venv) — зелёные.

## Post-review comment corrections (FIX-LABELS)

2026-10-16, лейн FIX-LABELS — только комментарии/докстринги, ни один assert/логика не изменены
(проверено побайтно: обратная замена только меток восстанавливает пред-правковые хеши). Сверка —
по источнику, не по ревью: `plans/features/soul-1/source-current-task.md` строка 185 (sha256 текста
строки `e9a5a0a9…`) = `source_text_sha256` записи `L00185` → req_id SOUL-13.2 (стенд); строка 189
(sha256 `265284ab…`) = записи `L00189` → SOUL-13.6 (6 падений pytest) в `soul-1/requirements-map.json`;
обе строки перехешированы независимо.

| Файл | Старый хеш, sha256[:16] | Новый хеш | Причина |
|---|---|---|---|
| `tests/test_webapp_teststand_guard.py` | `d35f17c5` (цитата ревью; стр. 1 и 16) | `379d53d7` | метка стенда → SOUL-13.2 (стр. 185) |
| `tests/js/glass_probe_test.js` | `c8e71eda` (цитата ревью) | `bffc3a50` | метка стенда → SOUL-13.2 |
| `tests/glass-teststand/glass-teststand.html` | `6628fb5a` (цитата ревью) | `2c209916` | метка стенда → SOUL-13.2 |
| `tests/glass-teststand/glass-teststand.css` | `b3e9b2b7` (цитата ревью) | `468ffb92` | метка стенда → SOUL-13.2 |
| `tests/test_tool_coordinator_round1026.py` | `b7001905` (ревью хеш не цитировало) | `ad431952` | метка стенда → SOUL-13.2 |
| `tests/test_unified_image_request_round1026.py` | `21c7e516` (ревью хеш не цитировало) | `b6b6856c` | метка стенда → SOUL-13.2 |
| `tests/test_mca16_experience_block_d_round1039.py` | `1adce018` (цитата ревью) | `86276461` | re-pin mca16 → SOUL-13.6 (стр. 189) |

§«Привязка кандидата» выше (стр. 14-17) остаётся снимком на момент ревью; после FIX-LABELS пункты
guard/node/html/css/mca16 там историчны — актуальные значения в таблице. Фикстура js `f8739e29`,
`matrix=7da3bcc9` не менялись; `v63-tails-report.md` обновлён по факту («Отпечаток» + запись
FIX-LABELS), его прежний хеш `76d08862` → `0ab94959`.

**Reverify после правки (`.venv`):** `node tests/js/glass_probe_test.js` → `JS-UNIT-OK glass-probe`
(exit 0); `pytest tests/test_webapp_teststand_guard.py -q` → `5 passed, 1 warning in 3.39s`;
`tests/test_tool_coordinator_round1026.py` + `tests/test_unified_image_request_round1026.py` +
`tests/test_mca16_experience_block_d_round1039.py` → `103 passed in 6.28s`.
