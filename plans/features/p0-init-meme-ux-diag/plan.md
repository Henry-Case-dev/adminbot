# P0-INIT-MEME-UX-DIAG — план срезов

**Источник:** `plans/owner_inputs/2026-11-11-p0-init-meme-ux-diag-corrective-excerpt.md`
(дословная копия user-owned `plans/current_task.md`, строки 11423–11552).
**Карта требований:** `requirements-map.json` (72 обязательства, 42 инвентарные строки + 85 доп. строк прозы).
**Граф срезов:** `slice-graph.json` (`openworkflow-slices-v1`).
**Статус:** планирование; в очередь исполнения добавляет Orchestrator.
**R0-INV закрыт (11.11.2026):** `evidence/r0/diagnosis-2.58.188.md`
(`sha256 27377ab82c88bf8c5324dca5573503dc0065a4a89b50af4427202afa849e6fbe`), 9 строк R0-VERIFIED,
`git diff --stat` по `services/`, `web/`, `handlers/` пуст. Причина `/meme` установлена (D7), перечень
дефектов D1-D7 разложен по срезам; по D6 добавлен под-срез **S5b**.

**Состояние срезов (12.11.2026).** S1-AXES и S2-ID приняты на `4c59a483` (13 + 8 строк `VERIFIED` по осям и
идентичности). **S3-OV одобрен Reviewer на `726736ee` двумя независимыми проходами, но НЕ задеплоен**: все 21 строка
среза стоят в `REVIEW`, ни одна не `VERIFIED`; доказательства и два ограничения — `evidence/s3ov/binding-726736ee.md`.
Этим же кандидатом закрылись UI-половины `P0IM-BAN-ENABLED` и `P0IM-AX-SERVER` (обе — `REVIEW`, остаются за S1-AXES);
`P0IM-BAN-NOETA` осталась `PENDING` из-за подстановки `now` в `next_check_ts`. Продакшен остаётся на `c087253d`.

## 0. Обязательная поправка о кодовой базе

Факты кода и все `write_scope` привязаны к **production-линии `release/2.58.188` (c087253d)**.

Локальный `master` (89be9d4f) **не содержит модуля «Инициатива/Мемы»**: `services/meme_initiative.py`,
`web/api/initiative_publications.py`, `handlers/meme_command.py`, `services/publication_coordination.py`
отсутствуют. Линии разошлись: release впереди на 1310 коммитов, master — на 180.

Следствие: Builder, начавший от `master`, физически не сможет «точечно править существующий модуль» и
перепишет его с нуля — это прямое нарушение требования владельца («не новый продукт, не новый
диагностический конвейер»). Ветвление только от `release/2.58.188`.

## 1. Объект и границы

Существующая «Инициатива»: текстовая инициатива, автоматические мемы, ручной `/meme`, обзор,
настройки, «Публикации», «Диагностика». Пять осей (`configuration`, `health`, `readiness`,
`last_attempt`, `last_delivery`) — **логические поля существующего read-model**
(`initiative_diagnostics`, `initiative_vitality`, `module_registry`, `publication_coordination`).
Это не новая БД, не параллельная state machine, не новый сервис телеметрии, не второй пайплайн мемов,
не новые LLM-вызовы ради наблюдаемости.

Классификация архитектуры: **`ARCHITECT_ADJUSTMENT_REQUIRED` уже закрыт** документом
`plans/features/p0-init-meme-ux-diag/architecture.md` (`DESIGN READY`, сверка по `c087253d`). Architect
зафиксировал read-model (`axes` аддитивно внутри `collect_mechanism_diagnostics`) и идентичность
(родитель — существующие `job_id` журнала мема и `trace_id` `mca_events`, **новых колонок и таблиц нет**,
миграции нет). Для S1/S2/S4/S5/S6 действует `ARCH_REUSE_CONFIRMED`; повторный Architect-проход не нужен,
A0-ARCH остаётся точкой сверки, а не ожиданием нового решения.

## 2. Волны и срезы

| Волна | Срез | Зависит от | Пишет | Почему один срез |
|---|---|---|---|---|
| 0 | **R0-INV** | — | `evidence/r0` (только документы) | Один проверяемый результат: доказанная причина `/meme` или точный пробел доказательств. Ноль изменений product-кода. |
| 1 | **A0-ARCH** | R0-INV | `arch/` (документ уже есть: `architecture.md`, DESIGN READY) | Одна точка сверки контракта: единый `run_id`-родитель + `incomplete_historical` для старых строк. Решение зафиксировано, ожидания нового прохода нет. |
| 1 | **S1-AXES** | R0-INV | `services/initiative_diagnostics.py`, `web/api/initiative_vitality.py`, `services/module_registry.py`, `tests/test_meme_init_diagnostics.py` | Один контракт ответа: пять осей на механизм из существующих полей. |
| 2 | **S2-ID** | A0-ARCH | `services/meme_initiative.py`, `services/initiative_observer.py`, `web/api/initiative_publications.py`, `handlers/meme_command.py`, `tests/test_initiative_publications_api.py`, `tests/test_meme_pipeline_api.py` | Одна связная идентичность попытки (мем и текст) и корректный учёт. |
| 2 | **S3-OV** | S1-AXES | `web/app.js`, `web/index.html`, `web/static/app.css`, `tests/js/initiative_ui_rework_test.js` | Один экран: обзор с двумя карточками и пятью осями. |
| 3 | **S4-TRACE** | S2-ID, S3-OV | `web/app.js`, `web/static/app.css`, `web/api/initiative_publications.py`, `tests/ui_initiative_rework_e2e.py`, `tests/test_initiative_publications_api.py` | Одна связная трасса попытки + защищённый доступ к полным текстам. |
| 3 | **S5-MEME** | S2-ID | `handlers/meme_command.py`, `services/publication_coordination.py`, `tests/test_meme_command_autodelete.py` | Один механизм: ручной `/meme` от получения команды до снятия приоритета. |
| 4 | **S5b** | S5-MEME | `services/publication_coordination.py`, `services/meme_initiative.py`, `tests/test_publication_binding_delivery.py` | Один инвариант доставки: оплаченное изображение не теряется при `publisher_not_bound`, квота и факт отправки согласованы. Сериализован с S5-MEME: тот же файл координации. |
| 5 | **S6-FRESH** | S4-TRACE, S5-MEME, S5b | `web/app.js`, `services/initiative_diagnostics.py`, `web/api/initiative_vitality.py`, `services/publication_coordination.py`, `tests/test_initiative_delivery_telemetry.py` | Одна сквозная корректность: чат, время, свежесть, просроченные маркеры. |
| 6 | **S7-ACCEPT** | S6-FRESH | `evidence/accept`, `tests/test_p0_init_meme_acceptance.py`, `tests/ui_p0_init_meme_e2e.py` | Одна независимая приёмка по матрице §8 и релизная проверка. |

Параллельные писатели: **максимум 2** одновременно (волна 1 и волна 2/3). Причина — `web/app.js`
один на обзор, трассу и свежесть: UI-срезы сериализованы зависимостями, а не искусственными барьерами.

## 2a. Классификация дефектов R0-INV → срезы

Полная таблица с файлом:строкой — в карте (`defect_classification`) и в
`evidence/r0/diagnosis-2.58.188.md` §6-§7. Кратко:

| Дефект | Срез | Что доказывает |
|---|---|---|
| D1 `ready=false` → «выключено» при `configuration=true` | S3-OV | `web/app.js:8280-8282`, `8381-8383` |
| D2 истёкший `manual_priority_until` как текущая блокировка | S6-FRESH | `web/app.js:3262-3263`, `8463`, `8471-8476` |
| D3 `job_id=""` в ранних отказах при уже созданном `jid` | S2-ID | `meme_initiative.py:2415-2435` против `2438` |
| D4 `record_attempt` теряет строки при sqlite lock (77/24 ч, 228/7 дн) | S2-ID | `meme_initiative.py:1148-1162`, `1471-1475` |
| D5 маркер не снимается на терминале; сбой записи только WARNING | S5-MEME | `publication_coordination.py:535-555`, `202-214` |
| D7 отмена на стадии изображения проходит молча (`CancelledError`) | S5-MEME | рестарт 09:21:08, 0 строк журнала |
| D6 `publisher_not_bound` выбрасывает оплаченное изображение (6/7 дн) | S5b | `meme_initiative.py:2701-2704`, `2220-2225`, `2917-2926` |

Отдельно: разница между чатами (время публикации, остаток кулдауна, квота, 7/8 против 0/8 сообщений,
зеркальные конфликты 1800 с, per-chat override) — **не дефект**; API отдаёт выбранный чат (`X-Chat-Id`
эхом как `chat_id`, без заголовка 422 и master-only фолбэк) — утечки scope нет.

## 3. Обязательные барьеры

1. **R0-INV → все.** Владелец требует сначала установить причину отказов `/meme`, потом править;
   Architect подтверждает это же: «Live до кода».
2. **A0-ARCH → S2-ID.** Контракт уже зафиксирован в `architecture.md`; точка сверки, а не ожидание.
   Если сверка найдёт расхождение — это возврат к Architect, а не решение Builder.
3. **S1-AXES → S3-OV.** UI не реконструирует оси из `ready`; он читает контракт.
4. **S2-ID → S4-TRACE и S5-MEME.** Трасса и ручной путь требуют устойчивого родителя попытки.
5. **S4-TRACE, S5-MEME → S6-FRESH.** Один и тот же UI-файл.
6. **S5-MEME → S5b.** Один и тот же `services/publication_coordination.py`; S5b не идёт параллельно.
7. **Все → S7-ACCEPT.**

## 4. Приёмка и живое доказательство

- Каждая строка — наблюдаемое поведение, а не «реализовано». Отказные сценарии (ранние гейты без
  `job_id`, обрыв после LLM A/B и после image API, пустое изображение, конфликт отправок,
  `delivery_unknown`, старые неполные записи) — обязательны.
- `live_required: preprod` для UI/поведенческих строк: Playwright + Browser Use на двух чатах,
  десктоп и мобильный Mini App, RBAC «другой чат», полная трасса без утечки секретов.
- `live_required: postdeploy` только у `P0IM-AC-POSTREL`: скриншоты двух чатов, артефакты реальной
  доставки/отказа, статус продакшена.
- Строк `owner_optional` нет. Владелец не является QA: тесты, БД, логи, провайдеры и UI проверяют агенты.
- Живые проверки не шумят в рабочие чаты: `/meme` и публикации — в тестовом чате.

## 5. Переиспользование (главный риск дублирования)

Полный разбор — в `requirements-map.json` → `reuse_analysis`. Итог:

- **Клонов нет (0).** Несколько source-строк одного обязательства ссылаются на один `req_id`
  (механизм гейта), а не порождают параллельные строки.
- **Переиспользованы как есть:** `EVOL-014/033/035/036/042`, `UR-20.1/20.2/20.3/20.5/20.9`,
  `MAC-S2-113`, `MAC-S15-12`, `CMV-ERR-07`, `NOST-10/12/18`, `INV-09/11`,
  `UI-MEME-RUNTIME-EFFECTIVE`, `UI-MEME-ACCEPT`, `ADMINUI-NO-NEW-SECTIONS`,
  `SD1-AMX-07`, `SD1-D2-06`, `SD1-D7-02`, `P0A-INIT-DIAG/PROOF`, `FC-07.1`.
- **Уже реализуют то, на что опирается корректировка:** `MEME-IIC-DIAG-TIMES`,
  `MEME-IIC-DIAG-UI`, `MEME-IIC-DIAG-COOLDOWN-CONFLICT`, `MEME-IIC-DIAG-NO-MIX`,
  `MEME-IIC-MANUAL-PRIORITY`, `MEME-IIC-MANUAL-RBAC-KEPT`, `MEME-IIC-LEDGER-EXISTING`,
  `MEME-IIC-DEGRADE-VISIBLE`, `MEME-CMD-BYPASS-GATES`, `MEME-CMD-KEEP-SAFETY`,
  `MEME-PROHIB-NO-DUP-PIPELINE`, `MEME-IIC-PROHIB-NEW-SCHEDULER`.
- **Поглощение PENDING-строк** (рекомендация Orchestrator, не действие PM):
  `HMF-UI-02` → `P0IM-OV-*`; `HMF-UI-06/07` → `P0IM-PB-*`; часть `HMF-UI-05` → `P0IM-PB-MANUAL`,
  `P0IM-OV-L3`. Остаются в силе и **не отменяются**: `HMF-UI-01/03/04/08/09/10`
  (вкладки настроек, адаптив, производительность) — новый источник их не переписывает.
  Пока это не сверено, суммы по эпику могут считать их дважды.

## 6. Что решает не PM

- Приём в очередь исполнения, `queue_position`/`blocked_by` и регистрация входа владельца
  (`owner_inputs`) — единоличная запись Orchestrator.
- Судьба `HMF-UI-02/05/06/07` (superseded_by) — Orchestrator после сверки.
- Контракт идентичности и миграция — Architect (A0-ARCH), не PM и не Builder.
