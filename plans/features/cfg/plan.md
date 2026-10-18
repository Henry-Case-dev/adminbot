# CFG-01…CFG-07 — план исполнения (редакция v0.7.1, 18.10.2026)

- Источник: `plans/features/cfg/source-cfg-addendum.md` — immutable snapshot (398 строк, SHA256 `2ED43009…6B10`).
- Карта: `plans/features/cfg/requirements-map.json` (strict_evidence + `slice-graph.json`): 246 inventory + 41 manual; гейт `--stage plan` — `errors=0`.
- Статус: ЗАРЕГИСТРИРОВАНО. Исполнение — строго ПОСЛЕ завершения текущей очереди `plans/current_task.md` (ADD-0.1), без остановки текущих задач и без нового свободно стоящего эпика (ADD-0.Q).

## Слайсы и порядок (12, строго последовательно)

| # | Slice | Суть | Live-обязательства |
|---|-------|------|--------------------|
| 1 | CFG-01 | Direct Chat burst/cooldown: effective-лимиты CHAT/GLOBAL, hot-reload, остаток времени, анти-обход | ui/live preprod (01.6, AC1/2/4) |
| 2 | CFG-02A | Суточная квота изображений в MiniApp: видима, управляема, реально влияет | ui/live preprod |
| 3 | CFG-02B | Новый частотный лимит: factory OFF, per-user/per-chat, отказ с остатком | ui/live preprod |
| 4 | CFG-02C | Жёсткая изоляция user_image ↔ summary_cover (учёт типов, отрицательные тесты) | preprod |
| 5 | CFG-03 | Аудит ВСЕХ параметров MiniApp: manifest на каждый, UI_missing, negative-тесты | hot-параметры ui preprod |
| 6 | CFG-04 | Формы/save/dirty/клавиатура/поворот (дополнение, не повтор U01/U07/HOTFIX/SOUL-11) | ui preprod + owner-E2E postdeploy (Telegram Android/Desktop) |
| 7 | CFG-05-Verify | Сверка deployed SHA + U08/SOUL-17 → REUSED_EXISTING/OWNER_VISUAL_CONFIRMED; без нового кода | postdeploy |
| 8 | CFG-06 | Единый фактчек-pipeline A–J: suitability+контекст, plan, evidence, вердикт, renderer, объединение H–J | provider/live preprod; live postdeploy (F.6, G.8, J.6) |
| 9 | CFG-07A | Анти-backstage аудит речевого маршрута (матрица SOUL не пересобирается) | prod-флаги postdeploy (A.1) |
| 10 | CFG-07B | «Использовать мат»: factory ON, GLOBAL/CHAT, Inspector | ui/live preprod |
| 11 | CFG-07C | public_speech_guard на точке outbound (все публичные каналы) | postdeploy (сквозные маршруты) |
| 12 | CFG-FINAL | ADD-2 №1–8 + процесс-контроль ADD-0 + регрессии current_task + итоговый отчёт | postdeploy (2.1/2.2/2.4–2.7) |

Зависимости: линейная очередь (документированные serial joins, ADD-0.1)
CFG-01 → 02A → 02B → 02C → 03 → 04 → 05-Verify → 06 → 07A → 07B → 07C → CFG-FINAL.
`CAN_PARALLEL_WITH`: нет (соблюдение «строго после очереди»); параллельно допустимы только текущая очередь и отдельный релизный лейн вне scope CFG.

## Пересечения и дедупликация (ADD-1, «не дублировать»)

- **Не второй SOUL-1**: CFG-05 = `OBSERVED_FIXED / REUSE_EXISTING` (U08/SOUL-17); новых рендеров, CSS, A/B и tier-тестов нет. Полигональный фон (реализация, геометрия, цвета, анимация, плотность) заморожен; glass — поверх него.
- **Не второй Fullscreen/навигация**: CFG-04 не трогает mobile-navbar, fullscreen-кнопку, логотип, шапку, safe-area (владельцы U01/U02/U07 + поздний HOTFIX; полный сценарий CFG-04D.5).
- **Не третий фактчек / не повтор B07**: CFG-06 объединяет существующие маршруты (System2/Temporal) в один контракт; карточка Temporal из B07 повторно не исполняется; CFG-06H–J уточняют 06B/C/D/G.
- **Не третье стекло**: стекло не перерабатывается; CFG-04/любые UI-работы лишь не должны регрессировать glass и фон.
- **Не второй Core / не второй per-chat Summary**: CFG-07 добавляет только дельту (анти-backstage, одно правило `profanity_use`, один egress-guard); CFG-03 расширяет B06/SOUL-1, переиспользуя подтверждённый evidence и ища UI_missing.
- Алиасы зафиксированы в requirements-map (`ADD-1.T1–T7`, `ADD-1.C1–C7`); у каждого пересечения один owning-task, дублирующая реализация запрещена (ADD-0.2).

## Статусная таксономия (ADD-0.5)

`IMPLEMENTED` → `TESTED` → `REVIEWED` → `DEPLOYED` → `LIVE_VERIFIED`; отдельно `OWNER_E2E_PENDING`, `FAILED/BLOCKED`.
Owner-only E2E не считается пройденным по мокам; обязательная функциональность не переводится в необязательный backlog.

## Процесс

1. Старт — автоматически после текущей очереди; нового сообщения владельца не требуется.
2. Каждый слайс: реализация → независимый Reviewer (acceptance слайса + инварианты ADD-1) → gate `review --slice --candidate` → штатный деплой (изоляция релиза и откат сохраняются) → live/owner-проверки → gate `release`.
3. Human Gate — только при фактической неразрешимой продуктовой альтернативе и только через Architect, точечно по этой альтернативе; независимые задачи продолжаются.
4. Owner-only проверки (Telegram Android/Desktop, визуальное подтверждение владельца, реальные продуктовые кейсы) не блокируют очередь: фиксируются как `OWNER_E2E_PENDING` с точным сценарием; «не ждать бесконечно» — после фиксации переходить к следующему независимому заданию.
5. Отчётность: время, человеческий язык, `%` и готово/всего, ссылки на SHA/tests; финал — сквозная сверка дополнения и старых обязательств (CFG-FINAL, ADD-2.8).
