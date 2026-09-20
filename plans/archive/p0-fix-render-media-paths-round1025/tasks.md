# P0-фикс после F1 — `p0-fix-render-media-paths-round1025` (hotfix2, внеплановый, после F1)

> **Триггер:** прод-инцидент сразу после деплоя F1 (`fe0f7bb`): (1) пустые config-разделы ИИ (`#/ai/llm`, `#/ai/names`, `#/smart-cache`, `#/memory/rag`) — render-регрессия F0 (`d5750fc`), проявившаяся в F1; (2) видео/ГС/аватары — контейнерный абсолютный путь локального Bot API.
> **Тип:** web (render) + backend (media/avatars пути) + cache-bust + тест-инструмент + ops.
> **Приоритет:** **P0** (прод-деградация). **Зависит от:** F1 (`ia-shell-navigation-round1025`).
> **Задачи:** **FIX 1…FIX 4** + регресс/ревью/деплой (отдельного ID-диапазона нет).
> **Статус:** ✅ **COMPLETED + MERGED + DEPLOYED + ARCHIVED** — коммит `fea2daa` (hotfix2); интеграция — `plans/ARCHITECTURE.md` **§54.1**.
> **Инварианты:** R16/R17/R18; F0/Эпик 2/промпты не тронуты; **Δ DDL = 0**, **Δ каталога = 0**; traversal-guard `_is_within_root` сохранён (fail-closed); единый cache-bust `?v=__APP_VERSION__`; бэкапы/теги `pre-round1025*`/`git stash@{0}` **не трогать**.

## Задачи

- [x] **FIX 1 — render:** `web/app.js::stickyFieldFailed` перенесён **computed → methods** (`web/app.js:2149`; вызовы `web/index.html:851,970` как `stickyFieldFailed(item.key)`). Причина: computed-геттер возвращал boolean → `TypeError` в render → пустой generic config-раздел. F0-контракт сохранён (только перенос объявления). Тест — `tests/js/round1025_save_state_test.js`.
  **Готово, когда:** config-разделы ИИ не пустые, тест зелёный.
- [x] **FIX 2 — media/avatars пути:** `services/media_download.py` — `CONTAINER_API_FILES_ROOT` (`:33`), `normalize_api_file_path` (`:60`, срез `<bot_id>:<token>`-префикса → host-корень), `read_host_file_bytes` (`:110`); `web/api/avatars.py` использует те же helpers. Traversal-guard `_is_within_root` (`resolve` + `is_relative_to`) сохранён, fail-closed (нет файла/вне корня/`OSError` → `None` → прежний `bot.download`). Тесты — `tests/test_media_local_path_round1025.py` (падали бы до фикса).
  **Готово, когда:** локальный путь container→host нормализован; guard fail-closed подтверждён тестами (видео/ГС/escape/аватары).
- [x] **FIX 3 — cache-bust/APP_VERSION:** `APP_VERSION` → **2.58.2** (`config/settings.py:1617`, `README.md`); `?v=__APP_VERSION__` покрывает tailwind/app.css/app.js/telegram-init.js/font.
  **Готово, когда:** единая версия для всех ассетов; клиент получает согласованные файлы.
- [x] **FIX 4 — matrix + тесты:** усилен `tools/ui_round1025_matrix.py` — непустой `/api/config` из `services/param_catalog.py` (458 items / 98 groups), маршруты `#/ai/{llm,prompts,smart-cache,names}` и `#/memory/rag`, **FAIL на console/pageerror** (снижает риск «ложно-зелёной» матрицы).
  **Готово, когда:** Playwright §71 — 0 нарушений, console/pageerror пусты.
- [x] **Регресс:** pytest **8003/0** (F1 — 7996/0), JS **21/21**; `node --check web/app.js` OK; `git diff --check` exit 0.
  **Готово, когда:** нет регрессий F0/F1.
- [x] **Ревью/аудит:** @Reviewer Approved; @Scanner **Critical 0 / High 0** (2 Medium → техдолг, 3 Low) — `plans/reports/round1025_hotfix2_scanner_audit.md`.
  **Готово, когда:** подтверждено.
- [x] **Деплой:** коммит `fea2daa`; прод обновлён, `/api/health` 200, `APP_VERSION` 2.58.2.
  **Готово, когда:** прод подтверждён.

## Live-гейт владельца (post-deploy, НЕ выполнено)

- [ ] ⏳ **Реальные видео/ГС/аватары:** загрузка/транскрибация реального видео и ГС; отдача аватара из локального Bot API (container→host путь).
- [ ] ⏳ **Разделы TMA:** config-разделы ИИ (`#/ai/llm`, `#/ai/names`, `#/smart-cache`, `#/memory/rag`) не пустые, в консоли нет `ReferenceError`.

## Техдолг (не блокеры, источник — `plans/ARCHITECTURE.md` §54.1 / `round1025_hotfix2_scanner_audit.md`)

- **M-1** — `services/media_download.py:153-155` логирует сырой `file_path` (содержит `<bot_id>:<token>`; маскируется глобальным `SecretMaskFilter`, но нарушает R17-контракт → логировать `PurePosixPath(file_path).name`/`sanitize`).
- **M-2 (avatars)** — `web/api/avatars.py:199-201` `exc_info=True`: `SecretMaskFilter` мутирует только `record.msg`, **трейсбек не маскируется**.
- **TOCTOU-guard** — проверка `exists()` перед копированием (гонка check-then-use) не закрыта.
- **vendor-скрипты без `?v=`** — `telegram-web-app.js` / `vue` / `chart` (L-2 §53).
- **matrix** — `tools/ui_round1025_matrix.py::_config_stub()` при сбое импорта `param_catalog` молча даёт пустой stub (L-2).
- **Low:** тавтологичный ассерт в `round1025_save_state_test.js` (L-1); нет регресс-тестов на symlink/двойной префикс (L-3).
