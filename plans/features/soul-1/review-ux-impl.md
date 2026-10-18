# REVIEW-UX-IMPL — независимое ревью UX-волны «Речь и характер» (P0A-UX)

| Поле | Значение |
|---|---|
| Кандидат | uncommitted поверх `1ce011af`: 10 файлов (sha256_12 — все совпали) + untracked `plans/features/p0-save-init-ux/evidence/ux-impl/**` |
| Вердикт | **Approved** — структура/компактность/сохранение/§10 подтверждены кодом, прогонами и скриншотами; остатки зафиксированы |

## 1. Состав и дисциплина

* 10/10 файлов совпали по sha256_12; `services/**` — 0 изменений; прочие dirty-треки — только чужие/родительские `plans/**` (в т.ч. PNG лейна glass-tiera) — не смешаны; новый e2e — untracked (новый) ✓.
* Диффы ограничены: `index.html` — все хунки внутри шаблона речи (7467–10320); CSS — только `.speech-*`-селекторы (+ их media-queries), глобальная палитра/стекло/полигон не тронуты; `web/api/speech.py` (+22) и `memory_agi.py` (+31) — по делу (детали карточек TJ-3; §10).

## 2. Структура и техмусор

* 4 группы из серверного payload; `data-speech-groups/-card/-menu/-savebar` в html; 10 карточек — рендер (e2e).
* Техмусор: html-грепы `owner_setting`/`fac:`/`trailing_period.hard.strip`/`emoji.hard.off`/`write_error`/`document_default` = **0**; в `app.js` коды живут только в картах подписей/ошибок (18959/18961/19138) и наружу не рендерятся (e2e §5.2 + routing-тесты это пиннят); «Для разработчика» = 0, «Все инструкции» — есть ✓.

## 3. Компактность

* Media `(min-width: 360px) and (max-width: 599px)` (ровно 2 кол.) и `(max-width: 599px)`; тач-цели ≥44; `safe-area-inset`; sticky `speech-savebar`; `data-autogrow` + autoGrow (40vh) и «Развернуть» (только ≤599px/landscape); скриншоты 390 (2 кол.), 320 (1 кол.), ⋯-меню, фуллскрин-редактор, 503 — без горизонтального переполнения; e2e на 6 вьюпортах — overflow==0, failures=0 ✓.

## 4. Сохранение, scope, guard

* `speechErrText` (4 кода → человеческие причины; 503-фолбэк; человеческий detail — «как есть») + `speechSaveFail` (409-валидация → «исправьте и сохраните снова»; 409-конфликт → «обновите данные»; 422 → «Выберите чат»; 503 → тост + «Повторить сохранение»; 403/401 как прежде); все speech-обработчики переведены ✓.
* Dirty per-edition (`coreFull/coreCompact/style/expression`) + открытая форма примера (`hasUnsavedEdits` дополнен §6.4.2); шапка «Есть несохранённые изменения: N»; `_dirtyLeaveGuard` в трёх точках (смена scope 6466, смена маршрута 9493, закрытие модалки 9915); `resetSpeechState()` в `setActiveChat` **после** guard (6529) чистит черновики/меню/секцию и перенастраивает scope нового чата + `speechScopeTouched={}`; scope — per-section (`speechScopeTouched`): e2e подтверждает, что смена scope в «Характере» не меняет «Правила письма», а стиль уходит со своим chat-scope; сценарий «смена чата с черновиком» — диалог, сброс на витрину, 0 POST и никаких чужих данных ✓.

## 5. §10 (ностальгия)

* `web/api/memory_agi._scenario_active(last_user_ts, now, silence_sec)` = `last_user_ts + int(silence_sec) > now` (None → False) — **та же формула**, что в `services/nostalgia_worker.py:418` (`active = last_ts + silence_min > now`, `silence_min = int(...)*60`); вызов — `int(silence_min) * 60`; payload `active`/`scenario` — в трёх состояниях (silence/cooldown/ready), прежние поля не изменены.
* `nostalgiaLabel`: приоритет cooldown → active → ready; **legacy «Тишина: N/M мин» сохранён** для payload без `active`; новые тексты «Живая беседа: вспомнит по контексту» / «Затишье: готово вспомнить прошлое».
* Тесты дополнены: `routing_test.js` (legacy-таймер, active/idle, приоритет кулдауна, не-показ кодов) и `test_webapp_round1013_f5_ui.py` (формула A/B против воркера, оба контура, bool-скаляр) ✓.

## 6. Прогоны (мои)

| Прогон | Результат |
|---|---|
| NEW `tests/ui_p0a_ux_speech_compact_e2e.py` (скрипт; `pytest` его не собирает — это ожидаемо) | **failures=0, POST=21** ✓ |
| `tools/ui_soul1_w6_speech_e2e.py --no-shots` | **failures=0, POST=16** ✓ |
| `pytest tests/test_soul1_w6_speech_ui.py` | **23 passed** ✓ |
| `pytest tests/test_webapp_round1013_f5_ui.py tests/test_p0_persistfix_speech_chat_scope.py` | **38 passed** ✓ |
| JS-sweep `tests/js/*_test.js` (node) | **PASS=87 FAIL=0** ✓ (+`routing_test.js` JS-UNIT-OK) |
| RED-before | `red-before.txt`: «групп витрины: 0» → отсутствие `[data-speech-menu='core']`; структурно: `data-speech-groups/-menu/-savebar/-autogrow` в HEAD = 0 ✓ |
| Glass before/after | множества FAIL **идентичны** (45 FAIL-строк в каждом; диффы — только шумовые `lens`-метрики); все — пре-существующие `lens_edge_*`/`ab_edge_refraction` вне `.speech-*` ✓ (в отчёте «46» — минорное расхождение счёта) |

Замечание: W6-инструмент по умолчанию пишет отчёт в **трекинутый** `plans/features/soul-1/evidence/w6/ui-report.json`; при моём ре-ране файл был изменён и я восстановил его (`git checkout --`) — рекомендую перенаправить вывод в свой evidence-каталог.

## 7. Чеклист §9 (30 пунктов)

Все 30 разобраны в `report.md` с привязкой к e2e/W6/live. **п.23** (перезагрузка MiniApp) принят с примечанием: read-after-write идёт через `loadSpeechSection(force)`, серверный round-trip — зона PERSIST-FIX (независимо проверена в REV-PERSIST-FIX, тесты зелёные); симуляции полной перезагрузки браузера нет — допустимо, не блокер.

## 8. Остатки

* **§10 дедуп**: формула A/B продублирована в `web/api/memory_agi.py` (стоп-условие лейна запрещало правки `services/**`) — follow-up бэкенд-лейну (общий helper), сейчас закреплено тестом.
* W6-fixture drift (`examples.starter`/telemetry/ab) — чужая зона; инструмент сделан устойчивым.
* Glass `lens_edge_*` — пре-существующее/environmental (идентично до/после).
* Нит из §6 (W6-инструмент пишет в трекинутый каталог soul-1).

## Итог

Волна реализована в заявленном объёме: витрина/иерархия и техмусор, компактность и мобильные механизмы, честное сохранение и изоляция чатов, §10-формула с legacy-совместимостью. Все ключевые прогоны воспроизведены мной, RED-before структурно подтверждён, glass-регрессии отсутствуют. **Approved.**
