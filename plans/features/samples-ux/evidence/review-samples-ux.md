# REVIEW — samples-ux (ADD-SAMPLES-UX), lane REV-SAMPLES-UX

Дата: 20.10.2026 (вечер). Кандидат: `29b91004b52325c8a97a4bc387caeeda70b21668` (HEAD рабочего дерева; services/web/tests чистые — прогоны = кандидат).
База диффа: `7142ffcf` → `29b91004`, ровно 21 файл; `services/factcheck*`/`tool_router` в диффе отсутствуют (factcheck-runtime не тронут — проверено).

## Вердикт лейна: **Approved** (блокеров нет)

## Прогоны (все на кандидате, самостоятельно)

| Набор | Результат |
|---|---|
| tests/test_samples_factory_persist.py | **11 passed** |
| tests/test_samples_categories.py | **12 passed** |
| tests/test_samples_fewshot.py | **16 passed** |
| tests/test_samples_acceptance.py | **8 passed** (вкл. структурный zero-live) |
| tests/test_samples_ui_e2e.py (venv, браузер) | **1 passed** = 6 сценариев (portrait/landscape/desktop/persist/factory) |
| tools/ui_samples_ux_e2e.py — повтор соля с --shots | failures=0, POST=7 |
| tests/ui_p0a_ux_speech_compact_e2e.py (venv, напрямую) | failures=0, POST=22 |
| tests/test_add_exp_expression.py | 36 passed (пины §2 обновлены на спеку, F3-тексты отсутствуют) |
| tests/test_mca17c_invariants_round1047.py | 8 passed (user_version 37, ресанкция в коммите) |
| tests/test_unified_core_route_coverage.py | 18 passed (CONTRACT) |
| tests/test_soul1_w4_sample_library.py (§6 регресс) | 20 passed |

Итого pytest: **130 passed, 0 failed** + браузерные e2e 0 failures.

## Проверки по срезам (независимо, не по отчёту Builder)

- **§3 persist (главный риск)**: tombstone по seed_key (`delete_sample` UPDATE, не DELETE; owner-строки — физический DELETE); оба сида skip по существованию строки (tombstone не воскресает, force инертен — путей неявного force нет: структурный тест единственного ручного эндпоинта seed); restore только `confirm=True` (428 без подтверждения), restore одного не трогает остальные, `factory_seed_absent` хранит данные владельца; edit→seed→persists с меткой owner_modified (поля OWNER_MODIFIED_FIELDS, одобрение/архив метку не ставят); revision_conflict без потери. Эмпирическая проба tombstone/seed/restore — согласована.
- **§1 категории**: ровно 3 категории записи + legacy (только миграция); явное поле `expression_mode` (тег режим не создаёт — selection и валидация на поле); v37-миграция на legacy v36-фикстуре: аддитивные колонки, бэкфил mat/humor, `other` НЕ переклассифицирован, id/revisions/approved/updated_at сохранены, повтор no-op; серверная валидация/выдача/фильтр/отбор/блоки/why категорийны.
- **§2 тексты**: независимая байт-сверка спека (source-*.md) == runtime `PROFANITY_INSTRUCTIONS` == тест-пины (EPISODIC/FREQUENT); OFF без изменений; inherit не тронут; жанровых исключений нет (EXPRESSION_HEADER вне диффа). Fingerprint: `factory_set_fingerprint()` вычисленный == пин `64ec1c60e278`; директивы Expression в factory-набор не входят (проверено `factory_texts()`) — bump не требовался, замечание reconciliation (d).3 по прецеденту F3 оказалось избыточным (на результат не повлияло).
- **§5 few-shot**: три различимых блока `<General_Examples>`/`<Examples>`/`<Expression_Examples mode="…">`; MAT — только approved+active+effective-режим по полю; мат-пример не становится юмором по словам (тесты на совпадение слов); bounded 1–3/ноль; отбор чисто детерминированный — **0 доп. LLM-вызовов** (проверено по коду select_samples/resolve_refs/why); честные причины, «Нет данных о последнем выборе» без симуляции (WHY_NO_DATA).
- **§4 UI**: DOM-e2e (6 сценариев) + собственные скриншоты 360/390/667/1280 (list/editor-mat/landscape/desktop): иерархия §4.1 соблюдена (нав+заголовок+пояснение → 3 вкладки одной строкой → покатегорийные счётчики → поиск+фильтр+«Добавить» → колонка карточек без SQL/JSON, подпись «Категория · GLOBAL/CHAT · Заводской/Мой/Изменено владельцем»); редактор — отдельный экран (категория из вкладки; Мат→режим; Юмор→приём; Общие→без обоих; «Назад» предупреждает; «Используется»=approved+active; аккордеон «Дополнительно»); заводская карточка — плашка+посмотреть исходный+restore по подтверждению; сравнение — «Отмена» по умолчанию; горизонтальный overflow 0px (замер в landscape и desktop); CSS — только новые классы `.speech-examples-*`/`.speech-sample-*`, токены/flex/min-width:0, без координат/DPI; шапка/фон/навигация приложения не перестроены (дифф index.html ограничен секцией «Примеры», app.js:2868 — только state-поля раздела).
- **§6**: w4-регресс 20 passed; «Пожелания своими словами» осталась в Expression (4-й категории/карточки нет); CRUD/approve/archive/глобал-чат/права покрыты acceptance-тестами.
- **§7 запрет live**: в диффе нет кода отправки сообщений (grep по send-паттернам — единственное совпадение: список запрещённых токенов внутри самого структурного теста); `test_no_live_send_helpers_in_this_module_source` присутствует; owner_live_checks §7 — 2 пункта PENDING_OWNER-E2E (MiniApp на устройстве; живой цикл правка/удаление→деплой→сохранилась), не гейты.

## Гейт requirements_gate

- `--stage plan`: **EXIT 0** (inventory=48, manual=29, errors=0).
- `--stage review`: структурный FAIL — `candidate_commit` в карте пуст и все строки PENDING (ledger-привязки не заполнены). По брифу это пост-вердиктная работа Orchestrator'а: **ledger-долг** — заполнить candidate_commit=29b91004, привязки evidence к строкам (в т.ч. artifact_path), проставить статусы по реальным доказательствам, повторить `check --stage review --slice ... --candidate ...` до ALL slices и `--stage release` после деплоя. Статусы карты честны (никаких фиктивных VERIFIED).

## Находки

**(a) Блокеры — нет.**

**(b) Неблокеры (рекомендую тот же визуальный cleanup):**
1. `restore_factory_preview` (services/mca_sample_library.py:1172) вызывает `list_samples` без `include_tombstoned=True` → удалённые владельцем заводские карточки не попадают в массовое сравнение, проверка `row.get("tombstone")` (:1180) — dead-check (подтверждено эмпирической пробой: preview ids=[2], tombstoned=1 вне списка). Данные не теряются, удалённые карточки остаются видимыми/восстанавливаемыми в группе «Удалённые заводские», все restore по-прежнему confirm-gated. Ремонт: одна строка (+ строка в preview-тест на tombstone-пункт).
2. Бейдж «Используется» ломается посередине слова при узком экране + длинном заголовке (скриншот list_360). Косметика: `white-space: nowrap` на бейдж/перенос на отдельную строку.
3. Существующий bulk-Inspector `POST /speech/examples/why` (web/api/speech.py) вызывает `select_samples` без `category=` — диагностический пул не разделён на humor/general блоки (в построчных причинах категория указывается; новый покарточный why полностью категорийный). Дрейф диагностики, не контракта.

**(c) Вне скоупа**: замечание reconciliation (d).3 о необходимости F8-bump — по факту директивы не входят в factory-набор (проверено), bump не требовался; зафиксировано, чтобы будущие карты не требовали лишнего bump.

## Живые пункты (owner_live_checks, PENDING_OWNER-E2E, не гейты)
1. MiniApp на реальном устройстве: раздел «ИИ → Речь и характер → Примеры» — вкладки/редактор/заводские действия читаемы, клавиатура и safe area не перекрывают.
2. Живой цикл «правка/удаление заводской карточки → штатный деплой/рестарт → правка сохранилась, удалённая не вернулась».

## Привязка
Кандидат: 29b91004b52325c8a97a4bc387caeeda70b21668. Любое изменение кода/конфига после этого прогона инвалидирует доказательства — перед релизом перепроверить затронутые пункты.
