# C3 — ограничения и RFL (не owner QA)

- **Натуральный двухоконный 409** — RFL: детерминированные сценарии двух клиентов/
  stale token покрыты Python и node; реальное второе окно не открывалось.
- **Натуральный долгий запрос с отзывом прав** (S4-176/S10-17) — RFL: recheck
  проверен детерминированно (`ChatParamsConflict` + `access_for` на recheck);
  реальная LLM/long-publication не запускалась (вне C3).
- **Реальный local_admin TMA-сеанс** (S8-524) — RFL: backend-матрица 401/403/200
  и UI-состояние 403 проверены; live TMA не запускался (запрещён рамками задачи).
- **Live TMA вообще** — не запускался; все UI-прогоны — локальный стенд
  (`http://127.0.0.1:8813`) с детерминированными API-стабами и TMA-stub.
  Browser Use — реальный локальный Chrome, но не production-TMA.
- **Production DDL/constraint** — проверены исходником `services/pg_db.py`
  (`DROP IF EXISTS` + `ADD` superset, идемпотентно) и unit-тестом; фактическое
  применение на PostgreSQL — при деплое 2.58.234 (вне C3; deploy/SSH не выполнялись).
- **S8-LEG-01** — инвентарь read-only; legacy-маршруты **не удалялись** и не
  мигрировались. `edit_humor_library`/`edit_persona` не имеют отдельного
  route-декоратора (классифицируются как действия в матрице) — зафиксировано
  в `inventory.json` как `catalog_without_guard`, не блокер C3.
- **F8 re-pin** — осознанный: route-set не менялся, новые маршруты в
  `access_router` (F8 сканирует только `@api_router`); `PARAM_CATALOG` не тронут.
