# Пост-деплойные миноры админки (F-1)

## Контекст и цель

Пост-деплойный бэклог Epic 85: задачи T-648…T-655, зафиксированы @PM 30.08 (MEMORY.md, board.md Backlog). Цель: довести качество админ-API до прода — атомарность записи, единый кастинг, актуальные права, корректный shutdown. Миноры ревью (APPROVE WITH MINOR N1–N3) + миноры хотфикса + известный дефект graceful shutdown после деплоя v2.51.0.

## Архитектурные привязки

- **84.12** — полная миграция параметров админки (реестр param_catalog, кастинг по типу, updated_by).
- **84.13.3** — запись /api/info через InfoService (файл-зеркало + PG); сейчас двойная запись в POST /api/info.
- **84.15.5** — graceful shutdown SIGTERM ≤10с (код реализован в bot.py:565-593; нужна прод-верификация @DevOps).
- **84.17** — аудит ревью: неатомарный POST /api/config (per-item set в routes.py:236-263), двойная запись updated_by (routes.py:497-515), устаревший docstring can_edit_param (deps.py:206-212).

## Границы

Только web/api + config_cache/hot_config/param_catalog. Бот-фичи (Telegram-хендлеры, память, медиа) не трогаем.

## Связи с другими фичами

- F-2 (`features/admin-debug-webview/`) — верификация через /debug_config.
- F-5 (`features/config-read-path-audit/`) — T-651/T-652 живут ЗДЕСЬ (в F-5 только ссылки, не дублировать).

## Критерии готовности

- POST /api/config атомарен: частичный успех невозможен (батч/транзакция).
- POST /api/info пишет один раз (InfoService), updated_by единый.
- can_edit_param документирует keys-категорию через can_view_key_value.
- Один хелпер каста на все точки входа; hot.get на cache-miss не кастует default.
- SIGTERM на проде: остановка ≤10с без SIGKILL (акт @DevOps).
- Полный pytest — 0 failed.
