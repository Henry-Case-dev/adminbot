# P0IM-OV-HONEST — две честности обзора инициативы (2.58.193)

Кандидат: `f8846e49` на базе выложенного `bcc090a3` (2.58.192, линия
`release/2.58.192`). Ветка `task/ov-honesty-258193`. Изменены только
`web/app.js`, `web/index.html`, `tests/js/p0im_ov_honesty_test.js`,
`tests/test_webapp_js_unit.py`. Meme-бэкенд и рендеринг трассы не тронуты.

## 1. Ложная пустота журнала

**Код до.** `web/index.html:1035-1040` (шапка модуля) и `1883-1888` (шапка
обзора инициативы) печатали `v-else` → «Последних действий в журнале нет».
Условие `v-if` — `moduleLastEventLine(workspaceModule)` (`web/app.js:22906`),
который возвращал пустую строку для `mod_initiative`, потому что
`moduleHealthView` знает только `mod_vision`/`mod_sleep`/`mod_experience`, а
`moduleScopeErrorFor` для инициативы пуст. Журнал при этом не читался вообще:
у того же чата `GET /api/initiative/publications` отдавал 327 строк.

**Код после.** Состояние строки двузначное (`web/app.js:22909`
`moduleLastEventState`): `event` (есть факт) или `unknown` (источник молчит).
Для `mod_initiative` факт берётся из УЖЕ загруженного снимка
`mechanism-diagnostics` — ось `last_attempt` двух механизмов, новейшая
(`initiativeLastActionFact`, `web/app.js:22936`); нового источника и нового
эндпоинта нет. При молчании источника печатается «нет данных».
Ложная ветка `v-else` удалена с обеих поверхностей (`1035`, `1880`).

**Строки до/после на реальном DOM** (Chromium, стенд
`tests/ui_initiative_rework_e2e.py`, `#/modules/initiative`, 1536×960, один и
тот же стаб-ответ `/api/**`):

| | `[data-module-last-action]` | в тексте страницы есть ложная пустота | карточка «Последняя попытка» |
|---|---|---|---|
| до (`bcc090a3`) | `Последних действий в журнале нет` | да | `15.01 08:03 UTC · автоматически · бот решил ответить` |
| после (`f8846e49`) | `Последнее действие: 15.01 08:03 UTC · Текстовая инициатива — бот решил ответить` | нет | то же (не тронуто) |

Снимки: `overview-before-1536.png`, `overview-after-1536.png`
(прогон `probe_overview_line.py`, оба дерева, только чтение).

## 2. Время в карточке: какое поле и какая подпись

Вопрос (а) — **какое поле кормит показанное 16:42**. Показанное в
«Последней попытке» — это `last_attempt.at`:
`web/app.js:4786` `iniAttemptAxis(b.last_attempt, tz)` → `at` →
`turnShortWhen` (`web/app.js:5318`, минуты, без округления). Ветка
«Дальше» — отдельная: `iniReadinessAxis` печатает `next_eligible_at`
(`web/app.js:4454-4470`) и при `16:41:54` даёт `16:41`, а не `16:42`.
«Последняя проверка» — третье поле: `checkText` из `block.lastCheckTs`
(`web/app.js:4879`), то есть `last_check_ts` сервера
(`services/initiative_diagnostics.py:2670`).

Вопрос (б) — **подпись верна**. «Последняя попытка» ← `last_attempt.at`,
«Последняя проверка» ← `last_check_ts`, `next_eligible_at` ← «Дальше».
Подмены нет, поэтому код подписи не менялся; добавлен тест, который её
держит.

Вопрос (в) — **это не ошибка выбора, а разные моменты съёмки**. Отбор
`last_attempt` берёт САМУЮ СВЕЖУЮ группу журнала: `ledger.attempts()`
`ORDER BY ts DESC` (`services/meme_initiative.py:1382-1418`), затем
`_meme_last_attempt` берёт первую группу и `max(ts)` в ней
(`services/initiative_diagnostics.py:2189-2253`). Пропущенные строки —
такие же попытки (`attempt_block`, там же 1945-1961), фильтра, скрывающего
`daily_quota_reached`, нет.

Сверка одного и того же payload 2.58.191: `last_attempt.at` текста
`16:27:40Z`, мемов `16:28:16Z`, `next_eligible_at` `16:41:54Z`, а кадр 2.58.191
показывает 16:42 в обеих подписях и «Сейчас: может сработать — ничего не
мешает» у текста, тогда как в том же payload текст был `waiting/eval_not_due` с
границей 16:41:54. Разные состояния одной карточки в одном кадре и в снятом
payload — значит payload снят раньше кадра (в БД мемов 14 строк в
16:42:00–16:42:59). То есть 16:42 — реальная ПОЗДНЕЙШАЯ попытка на момент
кадра, а не «сдвинутое» поле. Архивная метка `captured_at_utc=16:44Z` у того
payload неверна (это уже отмечено в `release-258192/deploy.md` §6).

## 3. Тесты и мутации

`node tests/js/p0im_ov_honesty_test.js` → `P0IM-OV-HONESTY-OK`.
Pytest-обёртка: `tests/test_webapp_js_unit.py::test_js_unit_p0im_ov_honesty`.

RED на базовом дереве `bcc090a3` (тест скопирован в пробное дерево):
`при живых строках журнала строка не назвала реальное действие: ` — и
`moduleLastEventLine` там действительно возвращает пустую строку.

Мутация A (вернуть ложную ветку + пустую строку при неизвестном):
`неизвестное состояние не названо честно: '' !== 'нет данных'` (exit 1).

Мутация B (ось попытки кормится `readiness.next_eligible_at`):
`подпись попытки текста не из last_attempt.at: 11.11 16:41 UTC · ...` (exit 1).

Обе мутации откачены (`git checkout -- web/`), дерево после откатa — green.

## 4. Прогоны

| Прогон | Результат |
|---|---|
| `pytest tests/test_webapp_js_unit.py -q` | 45 passed |
| `pytest tests/test_initiative_publications_api.py tests/test_meme_init_diagnostics.py tests/test_initiative_coordination.py tests/test_initiative_delivery_telemetry.py -q` | 141 passed, 4 failed |
| `tests/ui_initiative_rework_e2e.py` (реальный UI) | failures=2, те же 2 на базовом `bcc090a3` |

Предсуществующие (воспроизведены на нетронутом `bcc090a3`, к этому фиксу не
относятся): `test_initiative_coordination.py::test_act_on_opportunity_conflict_defers_to_intent`,
`::test_evaluate_phase_precheck_blocks_before_llm`,
`::test_t1_nostalgia_delegated_refusal_sends_nothing`,
`::test_t5_every_text_send_site_passes_publish_guard`; в e2e —
«после снятия override источник не „Исходный из кода“».

## 5. Что осталось непроверенным

- Живой прод не деплоился (в задаче не было деплоя): строки доказаны на
  реальных файлах в Chromium со стенд-API, не в Telegram WebView.
- Регион «Последние попытки» (5–10 строк) в обзоре не делался: это отдельная
  открытая строка `P0IM-OV-LIST`.
