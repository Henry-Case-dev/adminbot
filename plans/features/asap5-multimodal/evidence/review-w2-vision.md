# REVIEW - ASAP5 W2 VISION (leaf, read-only lens)

- Кандидат: `a3ac5c5efaa67011ea71b9fd16bfeca05cfe190e` (feat(asap5-w2-vision)), база `ad239f73`, ветка `task/asap5-vision`.
- Review-worktree: `C:/Code/Python/adminbot-wt-asap5v-rev` (detached @ a3ac5c5e).
- Скоуп: строки карты `REQ-VIS-STATUS-ACTUAL / -STATES / -PENDING-HONEST / -INTERMSG / -RACE / -PROMISES` + Часть III исходника (§12-§17); evidence билдера `w2-vision.md` (worktree билдера `adminbot-wt-asap5v`, docs-биндинг `ddb09c4f`).
- Ограничения: без code changes, без SSH/production/Telegram/LLM. Выполнено.

## Верификация по брифу

1. **Status truthfulness - VERIFIED.** Все поверхности читают фактическое durable-состояние: тул (`recognize_target`: ready + `no_text`-флаг; терминалы через `asset_vision_outcome` -> `terminal_tool_result`; pending только при живой задаче/истинном бюджете), рендер/Direct Chat (`render_media_context_async`: `NO_TEXT_LINE`, `ANALYSIS_FAILURE_LINES` по классу терминала; pending-регрессия сохранена), admin/API (`runtime_snapshot`: per-chat `WHERE m.chat_id=?`, глобальный + атрибуция `asset_id/chat_id`). Воспроизведено RED->GREEN на базе `ad239f73`: no_text propagation, enqueue-failure honesty, per-chat snapshot, terminal-during-wait — все 8 новых тестов красные на базе (не вакуумные), зелёные на кандидате.
2. **Promises - VERIFIED.** `services/tool_schemas.py`: один hunk, только `TOOL_RECOGNIZE_IMAGE.description` — обещание auto-send и «say you are going to look» удалены, pending = честное ожидание + приглашение переспросить, no_text != «не анализировалось», unavailable/failed = фактическая причина, disabled = модуль выключен. Текст только удлинён — квот/обрезок инструкций НЕТ (ADDENDUM #3 соблюдён). `not_configured` -> честная причина (mca_vision.py:516, `test_visible_reason_texts_cover_all_classes` зелёный в прогоне).
3. **Races - VERIFIED.** terminal-during-wait: event-wake + перечит durable-исхода, `test_asap5_w2_failure_during_wait_is_reported` (RED на базе -> GREEN). Double-job: coalesce singleflight `test_asap5_w2_coalesce_singleflight_no_double_recognition` (pre-green guard на базе; unique partial index + INSERT OR IGNORE). Lost-update: CAS `finish_media_analysis(expected_revision)` — `test_analysis_cas_stale_discarded` (tests/test_mca19_block_a_round1043.py:389) зелёный в прогоне 338. Новых записей/запросов в дифе нет (только read-only SQL) — новая гонка не введена.
4. **Scope/anti-templating - VERIFIED.** Диф: ровно 3 файла (+688/-16): `services/mca_vision.py`, `services/tool_schemas.py` (задокументированное отклонение, минимально), `tests/test_p0_vision_fix_core.py`. Новых провайдер/пайплайн/LLM-вызовов нет; квот нет; новых состояний нет (`TERMINAL_ANALYSIS_STATUSES` == словарь CHECK схемы БД; reason-коды существующие, есть в базе); W1 preview-семантика не тронута (mca19 W1-тесты зелёные в сете 338), `test_factcheck_media_2026_10_25.py` зелёный (сет 243).
5. **Regression - VERIFIED (в пределах заданных прогонов).** См. таблицу прогонов; расхождений с базой нет (на кандидате всё зелёное; RED-профиль новых тестов на базе совпадает с заявкой билдера 8/1).

## Прогоны (candidate a3ac5c5e, review-worktree)

| Сет | Результат |
|---|---|
| `test_p0_vision_fix_core.py` + vision/mca19 W1/addtr/media_download (сет билдера) | **338 passed** (совпадает с заявкой) |
| factcheck/context seam (`block_g`, `factcheck_context_cfg06`, `factcheck_media_2026_10_25`, `factcheck_p0_fc`) + тул-контур (`tool_schemas/loop/router`, `tool_calling_round1015`, `smoke_round1016`, `addtr_tools_minifix`) | **243 passed** (117+126, совпадает) |
| W2-тесты (-k asap5_w2) на кандидате | **9 passed** |
| W2-тесты на базе ad239f73 (врем. checkout базовых services/*) | **8 failed, 1 passed** (pre-green: coalesce guard) — совпадает с RED-профилем билдера |
| `py -3 tools/gen_param_registry_round1025.py --check` | **CHECK OK, EXIT=0** |

Полный сьют повторно не запускался (бриф ограничивает прогоны фокусными сетами); заявление билдера о профиле полного сьюта (39 failed = base-профиль) косвенно согласуется: все фокусные сеты зелёные, RED-профиль совпадает точно.

## Замечания

- NONBLOCKING (наблюдение): окно <= 2 c на истечении wait-бюджета — если джоба терминируется ровно в последнем slice сна, ответ может однократно быть pending/job_linked=true; следующее обращение потребителя отдаёт честный терминал (event-wake делает окно редким). Прежняя ограниченная семантика бюджета, §14/§16 не нарушает.
- NONBLOCKING: на кандидате a3ac5c5e строки карты REQ-VIS-* = PENDING/evidence пуст; биндинг VERIFIED живёт в docs-коммите `ddb09c4f` (зона PM). Содержание биндинга соответствует фактам (проверено).

## Вердикт лейна

**Approved (leaf)** — по всем 6 строкам REQ-VIS-* в рамках назначенного скоупа; вердикт по фиче — за parent Reviewer.
