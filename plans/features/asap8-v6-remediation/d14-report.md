# D14 — Help re-sync + финальная reconciliation (ASAP 8 v6, P1) — отчёт лейна

- Дата: 14.10.2026. База: HEAD `217c965` (release 2.58.77). Режим: writer.
- Контракт: `plans/ASAP8_v6_delta_after_F1-F9.md` §C D14 (+§E), синхронизация
  Help/гайда с фактическим shipped рантаймом v6, plans-state reconciliation.
- Прецедент механики: a1b3279 (asap7 F9 help resync) — generic-миграции
  `config_cache` по реестрам слепков, ΔDDL=0, Δroutes=0.

## 1. Каноны: INFO v8→v9, GUIDE v5→v6

Единственная кодовая точка — `services/info_service.py`:

- `DEFAULT_INFO_TEXT` v9: §10 +1 абзац — стиль обложки меняет внешность, а не
  сюжет; стилизованная версия, потерявшая сюжет, не публикуется (выходит
  базовая). Отражает C03 content-preservation + C03A honest base-fallback.
  Остальные 13 разделов не тронуты (структура §1..13 целa).
- `INFO_CANON_VERSION = 9`, слепок v8 заморожен байт-в-байт в
  `PREV_ASAP8V6_DEFAULT_INFO_TEXT` (реестр `KNOWN_INFO_SNAPSHOTS` = 8).
- `plans/docs/intelligence_user_guide.md` v6 — обновлены ТОЛЬКО затронутые
  секции (§5, §10, §12, §13, §14, §18; заголовки §1..19 целы):
  - §5 Досье: черновик правки под охраной, stale-ответ не переписывает
    правку (D01, коммит `6230fde`);
  - §10 Лимиты: у общей настройки видно переопределившие чаты, «Вернуть
    глобальные» одним движением (D07, `2ef6189`);
  - §12 Самостоятельность: живая воронка «возможности→намерения→решения→
    отправка», стадия/причина останова, тик пульса, hot-тумблер без
    перезапуска (C06A, `5c521fd`);
  - §13 Случайность: тумблер модуля настоящий, переживает перезапуск
    (D08, `e606ec8`);
  - §14 Опыт: цепочка «заметил→урок→проверил→применил→помогло/не помогло»,
    полезность «недостаточно данных» вместо нарисованных процентов
    (D05, `f2192b6`);
  - §18 Наблюдаемость: покрытие саммари (D12, `217c965`), стиль обложки
    сохраняет сюжет + recovery без второй Base и дублей (C03A, `8700628`),
    мобильная навигация сверху и dirty-only кнопка «Сохранить»
    (D13, `217c965`); попутно исправлена опечатка «Вделся»→«Выдался».
- `GUIDE_CANON_VERSION = 6`, слепок v5 заморожен байт-в-байт в
  `PREV_ASAP8V6_INTELLIGENCE_GUIDE` (реестр `KNOWN_GUIDE_SNAPSHOTS` = 5).
- `info_text.md` — байт-зеркало канона v9 перегенерировано.

## 2. Соответствие help-утверждение → рантайм (сверено с кодом)

| Help-утверждение | Shipped-носитель | Тест |
|---|---|---|
| Стиль сохраняет сюжет, чужая картинка не публикуется (INFO §10, GUIDE §18) | `services/cover_style_jobs.py` REASON_SEMANTIC_LOSS/`semantic_preservation_failed`, base_fallback с причиной; fail-soft гейт | `test_asap8_v6_c03a_style_recovery.py`, `test_asap8_f3_style_preservation.py` |
| Recovery без второй Base и дублей (GUIDE §18) | `services/cover_style_recovery.py` (recover_cover_style_jobs, bounded retry, idempotent linkage) | `test_asap8_v6_c03a_style_recovery.py` |
| Черновик досье / stale-guard (GUIDE §5) | `web/app.js` dossier request_token/identity-гварды на 8 путях | `test_asap8_v6_wa1_*` JS + py (6230fde) |
| Карта переопределений (GUIDE §10) | `web/api/routes.py` `/api/config/overrides-map` + popover quick actions | `test_asap8_v6_d07_overrides.py` |
| Воронка Инициативы + hot-тумблер (GUIDE §12) | `services/status_service.py` intent_snapshot; `web/app.js:3461+` лейблы «Возможности/Намерения/Решения/Отправлено»; джоба intent_heartbeat_tick | `test_asap8_v6_c06a_heartbeat.py`, `test_asap8_v6_c06a_status_ui.py` |
| Тумблер «Случайности» работает (GUIDE §13) | `services/config_cache.get_all()` синтезирует PG-only ключи каталога | `test_asap8_v6_wa1_config_cache.py` |
| Цепочка опыта + «недостаточно данных» (GUIDE §14) | `web/app.js:6973+` (usefulness known/(pos+neg), label «Недостаточно данных») | `test_asap8_v6_d05_experience.py` |
| Покрытие саммари (GUIDE §18) | `web/app.js:3830` « · покрыто сообщений: » в run-карточке | pin `TestHelpMatchesShippedRuntime` |
| Верхняя навигация, dirty-only «Сохранить» (GUIDE §18) | `web/index.html` bottom-nav удалён; `web/app.js:2544` чип dirty/saving | JS round1025 shell-пины, Playwright 34/34 (D1213-отчёт) |

Каждое утверждение проверено на носителе: новый тест
`TestHelpMatchesShippedRuntime` держит соответствие help↔UI в CI.

## 3. Доставка канонов (реальный канон-механизм)

- `tests/test_asap8_v6_d14_help_sync.py` (NEW, 24 теста, CONTRACT
  owner=ASAP8-v6/D14): маркеры v9/v6, инварианты (версии 9/6, реестры 8/5,
  `[-1] is PREV_ASAP8V6_*`, лестница гайда 1..5, байт-зеркало
  `DEFAULT_INFO_TEXT ↔ info_text.md`, `guide_version_for`), миграция v8→v9 и
  v5→v6 через `ConfigCache.init` (FakeConn-прецедент a1b3279), идемпотентность,
  ручная правка не затирается; grep-запреты жаргона (responseplan/planner/dag/
  extent/selfmodel/run inspector/неймспейс/эмбеддинг/namespace) и ложных
  обещаний — 0 попаданий; R17 (sk-/api_key/-100) — 0.
- После миграции `/api/info` и `/api/info/guide` отдают новые версии: тесты
  API-поверхности на реальном app+TestClient зелёные
  (`test_help_guide_round1014.py`, `test_info_handlers.py`,
  `test_webapp_api.py` 162). Live-проверка на проде — после деплоя 2.58.78
  (deploy-gate волны).

## 4. Пин-обновления (осознанные, без ослабления)

Абсолютные версии/размеры реестров 8→9, 5→6, 7→8, 4→5; индексы слепков
[-1]→[-2]/[-2]→[-3]; лестница (1,2,3,4)→(1,2,3,4,5); счётчик `<p>` 61→62
(новый абзац §10); фикс-версии guide-фикстур 5→6 в
`test_help_guide_round1014.py` (иначе легитимная one-time force-delivery v6
перекрывает «ручную правку» фикстуры — семантика теста сохранена).
Файлы: `test_asap7_f9_help_resync.py`, `test_help_ui_round1020/1022/1023.py`,
`test_info_service.py`, `test_help_guide_round1014.py`,
`test_mca21_guides_content.py`, `test_mca23_guides_content.py`.

## 5. Прогон

- Основная команда + соседи: **226 passed** (d14_help_sync 24 + round1020/
  1022/1023 + info_service + info_handlers + mca21/mca23 content +
  help_guide_round1014 + guide_delivery_round1016).
- `test_webapp_api.py` 162 passed; `test_config_cache.py` passed.
- EOL-инцидент (python-скрипт вставки слепков перевёл LF→CRLF на Windows)
  обнаружен по git diff --stat и полностью откачен конверсией в LF; финальный
  diff — только содержательные изменения (+549/−8 по канонам).

## 6. Plans reconciliation

- `plans/features/asap8-v6-remediation/f10-report.md` — НОВЫЙ, финальная
  reconciliation запуска (таблицы C01–C10/D01–D14, остатки, owner-pending).
- `plans/runtime_task.md` — финальное состояние запуска v6.
- `plans/workflow_state.md` и `plans/current_task.md` НЕ тронуты
  (Orchestrator / user-owned).

## 7. Остатки / риск

- Кандидат в дереве, НЕ закоммичен (по режиму лейна); коммит и деплой —
  Orchestrator. Поле deployed SHA в f10 оставлено под 2.58.78.
- OWNER_VISUAL_PENDING: вкус размещения Save-чипа, прод-данные run-карточек,
  live-поведение воронки/стиля (см. f10 §OWNER_VISUAL_PENDING).
- Помечено к сведению: `tests/test_asap7_f9_help_resync.py` числится
  untracked в git (не входит в HEAD-коммиты), пины внутри обновлены вместе с
  остальными; вопрос трекинга — не зона D14.
