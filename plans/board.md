# AdminBot — Kanban Board

## 📋 Backlog

## 🔧 In Progress

## ✅ Done

### Epic 1: Рефакторинг
- [x] T-001: Вынести API_TOKEN в .env / конфигурацию
- [x] T-002: Создать requirements.txt с закреплёнными версиями
- [x] T-003: Создать единую структуру проекта (config/, handlers/, filters/, services/, tests/)
- [x] T-004: Унифицировать обработку ошибок и логирование
- [x] T-005: Создать общий базовый класс для фильтров

### Epic 2: Новые функции
- [x] T-006 (F1): При возвращении Славы в чат → «ДОЛБОЕБ ВЕРНУЛСЯ» + new_chat_members fallback
- [x] T-007 (F2): Dead-page посты — рандомное фото + текст 2x/день + при входе
- [x] T-008 (F3): Каждые 5 сообщений → GIF через MessageCounterMiddleware
- [x] T-009 (F4): «КУЧА» → «ДАЛБАЕБ» с KuchaWordFilter (precise regex)
- [x] T-010 (F5): Военные слова → «трясло ебаное» для Славы (WarWordFilter)
- [x] T-011 (F6): Каждые 10 сообщений @Alan_Z (id 138811255) → reply random-фразой (UserIdFilter + DB counter)

### Epic 3: Тестирование и CI
- [x] T-012: Модульные тесты на все хендлеры (109 тестов, 12 файлов)
- [x] T-013: Тесты на все корнер-кейсы (пустой текст, нецелевой пользователь, границы)
- [x] T-014: Интеграционные тесты (unit tests покрывают все компоненты; H3 deferred)

### Epic 4: Документация
- [x] T-015: README.md с ироничной документацией

### Post-Review Fixes (7/7 applied)

### Epic 5: Багфиксы
- [x] T-016 (Kostik): Probability-based reply engine + extensible pool (KOSTIK_REPLY_PROBABILITY)
- [x] T-017 (Kucha): Fix KuchaWordFilter regex — remove "ек" from optional group
- [x] B1: KuchaWordFilter — precise declension matching regex
- [x] H1: Filter-level tests for VasyaFilter, StrictAdminFilter
- [x] H2: Legacy modules deleted (kostik, slavik, vasya)
- [x] M1: new_chat_members fallback for F1
- [x] M4: DB fixture stable (manual event loop)
- [x] M5: All settings env-configurable via settings.py
- [x] L3: on_shutdown cleanup hook in bot.py

### Remaining LOW (not blocking)
- [ ] H3: Dispatcher integration tests — deferred
- [ ] L1: README platform-specific Windows commands
- [ ] L2: Quoting in response text (reply_to covers)
- [ ] L4: MediaService cache invalidation
- [ ] L5: VasyaFilter translit order edge case
