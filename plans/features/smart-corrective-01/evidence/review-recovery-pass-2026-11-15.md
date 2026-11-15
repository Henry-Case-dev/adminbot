# REVIEW RECOVERY PASS — SMART-CORRECTIVE-01 (2026-11-15)

Независимый Reviewer: DeepSeek V4 Pro (`opencode-go/deepseek-v4-pro`), сессия `ses_e228ff988ffeMM3uyvHsR5Crn3`.
Проверенный код: `2b419aa2` (deployed 2.58.204), worktree `smart-corrective-recovery-r1`, чистый.
База/происхождение: `c97c06e4` (2.58.203), `d20a7f73` (2.58.199); все ключевые corrective-коммиты — предки `2b419aa2`.

## Вердикты

| Блок | Вердикт |
|---|---|
| Фактчек S13/S14/S15/S16/S17, SFC-12-09, FC Anchor: предмет, claim из reply/текста/изображения, вопрос и уточнения, анкер, фокус, evidence, partial, публикация | CONFIRMED (review-level) |
| Watchdog/recovery S5A–S5D: recovery, fencing/generation, queued/running, delivery_unknown, отсутствие повторной доставки, error_code, takeover_recovered, события, инциденты, наблюдаемость | CONFIRMED (review-level) |
| Промпты S6 Delivery/Guard/Activation, Checkup Label: редакция владельца, factory attestation, withheld после рестарта, версии/provenance/rollback, Core/Expression | CONFIRMED (review-level) |
| Вход/завершение S3/S4 и стыки | CONFIRMED (review-level) |

Обязательные сценарии фактчека: короткий `фактчек` без текста; `фактчек` в reply; `фактчек` с вопросом о материале; вопрос, отличный от темы публикации — подтверждены кодом и тестами.

## Независимые прогоны

Лично пройдено **101 тест** на `2b419aa2`: watchdog events 13; lifecycle+observability+recovery_scope 53; prompt_delivery 21; checkup_label_activation 9; FC anchor 2; input/completion 3.
Проверено ослабление тестов: `git diff c97c06e4..2b419aa2 -- tests/` затрагивает только VMQ; `test_smart_exec_learning_incidents` усилен (W-05/W-11), не ослаблен.

## Находки / ограничения

- Блокирующих IN_SCOPE/CRITICAL дефектов нет.
- **EVIDENCE_GAP:** live-постдэплой не подтверждён — реальная активация промпта в процессе бота, телеметрия живого чекапа, live-метрики фактчека остаются postrelease-наблюдением.
- **W-12** (причины шести инцидентов) требует production-данных; W-01..W-11 не блокирует.
- FC Anchor: тест `test_orchestrator_passes_full_material_to_plan` использует `inspect.getsource` (шов на уровне исходника), а не исполнение полного пути; покрыто planner/integration-тестами, но это ограниченное wiring-доказательство.
- Нестабильность окружения (рестарты) прервала часть полных наборов; для них прочитаны assertions и прогнаны ключевые тесты; прежние evidence фиксируют полные числа. Собственный mutation-run не выполнен (shell-сканер блокировал кастомные скрипты); приняты ранее задокументированные мутации при неизменном контракте.
- Прод не изменялся: ни записи, ни закрытия инцидентов, ни реального Telegram.

## Вывод

**Approved (predeploy review)** по всем четырём блокам; это не production-acceptance и не перевод строк в VERIFIED. Не подтверждены только live-наблюдения (S6-ACTIVATION, live-метрики фактчека, W-12) и `original_production_scenario` фактчека — они остаются postrelease_wait, не блокируя очередь.
