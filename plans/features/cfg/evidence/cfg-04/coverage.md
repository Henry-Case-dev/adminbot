# CFG-04 — покрытие 20 строк карты (кандидат, без деплоя)

Статусы: **READY_FOR_REVIEW** — код + кандидат-привязанное evidence, ждёт
независимого ревью; **READY_FOR_LIVE** — доказано локально/эмуляцией,
требуется preprod-прогон на deployed SHA; **PENDING_POSTDEPLOY** — только после
деплоя; **PENDING_OWNER_E2E** — честно не проверено (нет реального клиента).
Ни одна строка не объявлена `VERIFIED` этим лейном.

| req_id | что доказывает | evidence | статус |
|---|---|---|---|
| **CFG-04B.1** (L157) | один интерактивный save-CTA (панель); шапка — `role=status`, «N · не сохранено»; нет `@click=saveModalEdits` в разметке | `matrix.md` CTA 2→1 все 7 viewport; `TestOneSaveFlow`; `asap8_d1213` (пере-пин L157); `after.json.config_dirty.cta` | READY_FOR_LIVE |
| **CFG-04B.2** (L158) | safe-area `max(env,--tg-safe,--tg-content-safe)` ровно один раз; `--kb-offset` двигает панель; «Сохранить»/«Отмена» видны (в т.ч. ландшафт) | `matrix.md` pad 7.2→63.2/31.2, panel bottom при kb; `TestPanelSafeArea`; F9-пин; `ui/after/*.png` | READY_FOR_LIVE |
| **CFG-04B.3** (L159) | фактическая высота панели → scroll padding; последнее поле/каретка не под панелью; M-1 (`padding-bottom:0`) сохранён | `matrix.md` panel h 100→168.4 (320), overlap −28→−161.9; `TestLastField`; E2E last_field | READY_FOR_LIVE |
| **CFG-04B.4** (L160) | dirty из значений (возврат снимает); save ждёт ack, baseline не сдвигается при ошибке; cancel — только текущая форма | `TestDirtySaveContract`; `cfg04_forms_contract_test.js` §5; D13-пин `stickyFailed`/baseline | READY_FOR_REVIEW |
| **CFG-04B.5** (L161) | единый путь dirty/save для text/number/select/bool/key; «↪ Глобальное» отличимо; случайной активации при повороте нет | `TestDirtySaveContract::test_single_save_engine`/`test_chat_override_reset_is_distinct`; E2E orientation (кнопки не нажимаются) | READY_FOR_REVIEW |
| **CFG-04C.1** (L165) | <768 одна колонка без горизонтального скролла; 844/915 — две колонки, карточки читаемы | `matrix.md` grid 1/1 и 2/2, overflow=0; E2E `_main_blockers` (cardWidths) | READY_FOR_LIVE |
| **CFG-04C.2** (L166) | touch-зоны ≥44 (переключатель/кнопки), контролы не съезжают, источник значения виден | `matrix.md` toggle 44×24→44×44, кнопки 37.6/38→44; `TestLayoutAndTouch` | READY_FOR_LIVE |
| **CFG-04C.3** (L167) | полный ключ: title + раскрытие + копирование; русские title/description/value на месте | `TestTechnicalKey`; E2E key open/copy на 7 viewport (clipboard == ключ) | READY_FOR_REVIEW |
| **CFG-04C.4** (L168) | при клавиатуре форма сохраняет размеры, кнопки достижимы; числовая клавиатура/многострочные редакторы не ломаются | E2E kb (`top>=0`, кнопки в видимой области); `.modal-card` минус kb; `visual-check.md` | READY_FOR_LIVE |
| **CFG-04C.5** (L169) | фон/палитра/glass/композиция не менялись | `TestProtectedSurfaces` (токены), 178 проверок матрицы = master (0 новых падений), `ui/before` vs `ui/after` | READY_FOR_LIVE |
| **CFG-04D.1** (L173) | воспроизведение на актуальном MiniApp и причины в layout/CSS/JS | `baseline.json` (85 падений на master), `failures.md` (причина по каждому) | PENDING_POSTDEPLOY |
| **CFG-04D.2** (L174) | автопроверки 320/360/390/430 + 667×375/844×390/915×412 + поворот, DPR 2/3 | `tools/ui_cfg04_forms_e2e.py`; `e2e-log.json`; `matrix.md` | READY_FOR_REVIEW |
| **CFG-04D.3** (L175) | before/after: bbox контролов, overflow, первое/последнее поле, высоты, кликабельность, dirty/ошибка/клавиатура/ключ | `baseline.json`/`after.json` (полные bbox), `matrix.md`, `ui/before|after` | READY_FOR_REVIEW |
| **CFG-04D.4** (L176) | живой Telegram Android portrait+landscape + Desktop | — | **PENDING_OWNER_E2E** (честно; реального клиента в лейне нет, PET — не блокирующий gate) |
| **CFG-04D.5** (L177) | полный сценарий `limits.chat_burst_limit` → поворот → сохранить → реальное значение; override → GLOBAL | E2E: dirty поля `limits.chat_burst_limit` в модалке, save-ack стаб, поворот 390↔844; реальный сервер — после деплоя | PENDING_POSTDEPLOY |
| **CFG-04A.1** (L153) | поворот сохраняет ввод/scope/поле/dirty/скролл/маршрут, без скачка наверх | `after.json.orientation` (scroll 220→0 стало 220, active key, dirty 1); `TestOrientation` | READY_FOR_LIVE |
| **CFG-04.F** (L149) | не переделаны navbar/fullscreen/логотип/шапка | `TestProtectedSurfaces::test_header_navigation_not_rebuilt`; diff только узел чипа | READY_FOR_REVIEW |
| **CFG-04.B** (L179) | композит: нет перекрытий с нативными зонами, нет дублирующих сохранений, поля доступны после поворота | собирается из B.1–B.3, C.1–C.5, D.4–D.5 | PENDING_POSTDEPLOY |
| **ADD-1.T4** (L23) | CFG-04 = только формы/save/dirty/keyboard/orientation | `blast-radius.txt` (scope), diff-файлы | READY_FOR_REVIEW |
| **ADD-1.C5** (L34) | fullscreen-кнопка не тронута | `TestProtectedSurfaces`; JS fullscreen-тесты зелёные | READY_FOR_REVIEW |

## Остатки на live (не выдаются за PASS)
- **D.4** — реальный Telegram Android/Desktop; сценарий в `manual-checks.md`,
  статус `PENDING_OWNER_E2E`.
- **D.1/D.5** — воспроизведение/полный сценарий на deployed SHA; безопасная
  фикстура `limits.chat_burst_limit` с восстановлением.
- **Preprod** — B.1/B.2/B.3/C.1/C.2/C.4/C.5/A.1 на deployed кандидате.
