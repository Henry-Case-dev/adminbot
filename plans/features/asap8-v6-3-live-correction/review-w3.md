# REV-W3 — независимое ревью Wave 3 (asap8-v6-3-live-correction)

**Кандидат:** HEAD da58e24b (W3 = 2d95689 W3a + da58e24b W3b), база diff 1418d7.
**Дата:** 2026-10-16. Ревьюер: REV-W3 (leaf, read-only; отчёты Builder'а проверялись по коду, не принимались на веру).

## Вердикт: Approved (в объёме Wave 3; live/прод — Wave 4)

## 1. CORR-1 (фон заморожен) — VERIFIED
- git diff f1418d7 HEAD -- web/static/polygon-background.js = 0 строк; aurora-секции app.css/index.html — 0 строк ±.
- Единственное упоминание polygon в diff CSS — комментарий к B05.1-поверхности редактора; стек фона не менялся. Test-стенд только в glass-teststand.* (не production).

## 2. B05 редактор обложек — VERIFIED
- Разделение **реальное**: current = draft полей ввода, server = снимок (refs/preview/can_edit/preview_*); coverStyleLoadMeta пишет ТОЛЬКО в st.server; 
ext_issue_number → input только при !editorDirty (web/app.js 12348–12547). Это не «отключение polling»: в e2e polling жив (job started/done, meta_calls=2), выделение 13с неподвижно, DOM-метки __w3 не пересозданы.
- Opaque surface локальна: .cover-editor { background: var(--surface-1) }, bg alpha=1, canvas под оверлеем (e2e: центр рабочей области не канвас, B05.1 чеки).
- Guard не ломает save contract: ключи POST неизменны (e2e save_body_keys = 10 канонических), instruction берётся из draft, can_edit из серверного снимка.
- DoD-тесты осмысленны: setSelectionRange(10,60)+Range в pre, сэмплы каждые 300мс, taScroll, DOM-identity, dirty-draft не перетирается, wheel за оверлей не уводит, 100dvh/один скроллер/320 без overflow. **Перепрогнано на HEAD: 40/40** (артефакты ревью: OPENCODE_WORKFLOW_SCRATCH/rev-w3-editor/).

## 3. U06 style editor UI — VERIFIED
- Порядок секций в index.html: Профиль(1011) → Инструкция(1062) → Референсы(1116) → Проверка промпта(1173) → Test Edit(1269) → Результат(1327) → Подробнее(1421) — совпадает с ТЗ; метаданные сборки (edit_report) в <details>.
- Строка сборки одна: Style N · SceneAnchor M · Refs R · System S · Final F / Limit L (coverEditSummaryLine), класс cover-limit-over только при превышении; exact prompt — mono <pre> со скроллом + «Копировать»; copy==exact (clipboard_len 461 == final chars).
- Честное «неизвестно»: coverEditLimitText → «неизвестно», детали «Лимит: неизвестно — провайдер не сообщил лимит», compile unknown строка «Final 461 / неизвестно»; coverCompileFinalText только при status==='ok' — псевдоуспехов нет.

## 4. U03 Статус — VERIFIED
- Один блок Сна: единственная каноническая панель data-status-sleep; дубль-ряд бейджей из шапки «Мониторинга Интеллекта» удалён (e2e 
o_dup_sleep_badges).
- 1970-нормализация: _tsNormalizeMs (sec→ms ≥1e11-порог, None/''/Date, 0/отрицательные→null, epoch-мусор вне [1990,2100)→null) + _tsStatusLabel → «ещё не выполнялся». Покрыто js-тестами.
- «Здоровье памяти»: смысловые (mem-kv--semantic: Просрочено N + доступно поиску/перепроверка/вытеснено/режим + убеждения) ОТДЕЛЬНО от технических (mem-kv--tech), строки имя→значение, не pills.
- Воронки из W1-данных (не заглушки): web/api/memory_overview.py — task_jobs checkpoint counters (initiative.observe/experience.review), окна 24ч/7д из mca_events, liveness из memory_maintenance._initiative_observer_last_tick, last_application из mca_lesson_applications. TTL-кэш 60с.
- «Просрочено N» из MemoryManager.expired_memory_overview (W1), fail-open, RBAC global-admin.
- **Перепрогнано на HEAD: STATUS e2e 26/26, console 0 ошибок** (rev-w3-status/).

## 5. U04 Логи — VERIFIED
- #status-logs один физический экземпляр в конце Статуса (index.html 8383; прочие вхождения — комментарии).
- oversightTabs без logs (7 вкладок); loadLogs() — лениво при входе в Статус (14177–14183), на входе в Аналитику загрузки нет (комментарий U04 на 10045–10046).
- Легаси #/oversight?scroll=logs и ?tab=logs нормализуются к #/ (replaceState, без повтора скролла), якорь-скролл с измеренным sticky-offset, bounded-settle ≤5 попыток.
- RBAC/redaction: web/api не менялись (только 2 новых файла), backend логов нетронут; js-тесты лог-фильтров/счётчиков зелёные.

## 6. U05 Аналитика + 7viz — VERIFIED
Источники всех 7 (проверено по коду):
1. Цикл памяти — счётчики 24ч из /api/analytics/viz/process-activity (реестр+mca_events) + подписи cognitionStats; honest-пометки «событий нет — не нули».
2. Sankey-lite — те же durable-счётчики; ноль событий → полоса 0 (без фантомного бара).
3. Waterfall — существующий F4 /api/analytics/pipeline/runs/latest (нового API/поллера нет).
4. Heatmap — /api/analytics/viz/activity: mca_events day×hour; 	elemetry_enabled:false → честная причина, empty_reason:'no_events_in_window'; e2e heatmap_off_honest.
5. Карта зависимостей — реальные inputs/outputs реестра (edge = артефакт X во входах Y).
6. Timeline дат фактчека — уже загруженные temporalRuns (published/received/checked, date_source).
7. Popover overrides — D07 /api/config/overrides-map, scope-guard epoch.
- Эффективные статусы: словарь ТЗ («не запускался/работает с результатом/ошибка/не было условий/выключен» + честные not_instrumented/fallback) поверх egistry_snapshot+mca_events; 48 человеческих имён + fallback на purpose; tech-ID за «Детали».
- Ноль новых поллеров (единственный новый таймер — bounded settle setTimeout) и ноль новых CDN (все script src — локальный /static/vendor; новый ассет W2 — только lg-lens-map.png локально).
- **Перепрогнано на HEAD: ANALYTICS e2e 74/74, 21 скриншот** (rev-w3-analytics/).

## 7. B06/B07/B01 UI-хвосты — VERIFIED
- B06.1: Summary untimeGate: 'per_chat' — тумблер на чате активен, «не влияет; глобально» для Summary не показывается (per_chat-ветка notice); причина chat_off честная.
- B06.2: global-only карточки — read-only на chat/dm + «Настроить глобально» через существующий scope-канал; клиент-гвард setModuleState → error:'global-only' обоснован (backend 422 покрывает только models/keys/temporal, flags-ось пропустила бы инертный override).
- B07: секция «Время и источники» на вкладке настроек Фактчека — объяснение реального гейта 	emporal.tool_enabled (что включает/что НЕ выключает) + аварийная env-ось; режимы contextual/current/historical_truth/knowable_at_time; TTL-поля; display-оверрайды при Δкаталога=0 (прецедент M-F7-2).
- B01.4: профиль «Редко/Нормально/Активно» (rare/normal/active = канон initiative_observer) + группы limits_intent; master read-only на чате.
- Пин Temporal: mod_factcheck_temporal нет ни в MODULES, ни в реестре витрины (js-тест + e2e 
o_temporal_card).
- **Перепрогнано на HEAD: MODULES e2e — все чеки зелёные, включая RBAC-403 fail-open честный, 320/390 без overflow** (rev-w3-modules/).

## 8. B08 UI-карточки + f7 re-pin — VERIFIED
- display_title (fallback title→«Без названия»), content_status==='insufficient_sources' → бейджи «нет источников»/«сюжет не восстановлен» без success-раскраски; synopsis «пока не восстановлено» вместо выдумки.
- Три разные даты (события start—end / обнаружена / пересобрана), null → «нет данных».
- Участники ≤5 + «ещё N» с раскрытием; хронология с refs: url (права валидирует сервер) → кликабельно, иначе «в архиве» (ссылка не выдумывается).
- f7 re-pin жив: raw IDs (story_id/участники-ID/episode keys) только внутри <details data-stories-dev> collapsed.
- Скриншоты 320/390/1440/landscape в evidence; ANALYTICS e2e включает story-card чеки на HEAD.

## 9. Тесты (прогон ревьюером на HEAD da58e24b)
- 
ode tests/js/*.js — **84/84 файлов, 0 failed**.
- pytest: hotfix6/hotfix8/design_tokens/f7_stories/tool_coordinator/unified_image_request/memory_overview_api/b08_stories/f4 — **237 passed**.
- E2E перепрогнаны ревьюером на exact-кандидате: EDITOR 40/40, STATUS 26/26, ANALYTICS 74/74, MODULES — все чеки; артефакты в OPENCODE_WORKFLOW_SCRATCH/rev-w3-*.

## 10. B08/B11 backend (ранее ревьюванные) — регрессий нет
- N1 (stories_feed display-правила) и N2 (sys.path-бутстрап b11) исправлены в 8f9d9a0 (подтверждено фикс-нотой и тестами: b08_stories + f7_stories зелёные в прогоне 237).
- NB-1/NB-2 — в backlog, не блокеры.

## Anti-fake-аудит
- Виджеты: нули-от-балды отсутствуют — все empty-пути честные (telemetry_off, no_events_in_window, «событий телеметрии пока нет», ширина 0 вместо фантомного бара, «недоступно: причина»); e2e проверяет off-состояние.
- Re-pin'ы не ослаблены: CORR-1 (фон), f7 (raw IDs в collapsed dev), CSP-инвариант (локальные vendor-скрипты), отсутствие Temporal-карточки — интент жив и проверен на HEAD.

## Findings

**Блокеры: нет.**

**Nonblocking:**
- NB-W3-1 [RELATED_SMALL]: 	ools/ui_asap8_v63_w3_status_e2e.py не закоммичен (untracked), в отличие от трёх остальных e2e-тулов волны. Evidence U03/U04 воспроизводим (я перепрогнал на HEAD), но тул стоит закоммитить для durable-регресса. Ремонт: git add tools/ui_asap8_v63_w3_status_e2e.py + 1 прогон.
- NB-W3-2: fingerprint в w3-evidence-status привязан к CRC времени W3a (до W3b) — superseded перепрогоном на HEAD (см. §9); хранить как исторический.
- NB-W3-3: предсуществующий flaky 	est_direct_chat_concurrency (FakeDB-артефакт, документирован в baseline-pytest-b10.md) — зона B10/W4, к Wave 3 не относится.
- NB-W3-4: рабочее дерево содержит незакоммиченный services/disk_retention.py (D1-disk-diag) — вне скоупа W3; кандидат = HEAD da58e24b (не dirty-дерево).

## Ledger (объём Wave 3)
CORR-1 VERIFIED · B05 VERIFIED · U06 VERIFIED · U03 VERIFIED · U04 VERIFIED · U05 VERIFIED · B06-UI VERIFIED · B07-UI VERIFIED · B01.4-UI VERIFIED · B08-UI VERIFIED · f7-re-pin VERIFIED · B08/B11-backend-регрессии VERIFIED (нет).
Не в объёме этой волны: live/прод-поведение (Summary на реальной генерации, канари) — Wave 4.

## Binding
Approved действителен для exact da58e24b (дерево web/ без диффа к кандидату). Любое изменение web/app.js|index.html|app.css|web/api/{memory_overview,analytics_viz}.py инвалидирует соответствующие пункты.
