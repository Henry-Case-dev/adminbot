# MOD-ACL-UX-01 M2 — before/after effective state

Источник данных: fixture=plans/features/mod-acl-ux-01/reports/m2-impact-fixture.json (детерминированный, без БД)
Режим: read-only (только чтение существующих строк; значения не перезаписываются).

capability: 16 · чатов: 4 · изменённых пар (чат × capability): 3 · чатов с изменением поведения: 2

## Изменения по capability

### gate:dream — 2

- чат -300: OFF → ON (chat_state=inherit, source=global)
- чат -100: OFF → ON (chat_state=inherit, source=global)

### module:experience — 1

- чат -100: OFF → ON (chat_state=on, source=chat)

## Чаты с изменением поведения (поштучно)

- -300: gate:dream
- -100: gate:dream, module:experience

## Без изменений — 2 чатов

-400, -200

