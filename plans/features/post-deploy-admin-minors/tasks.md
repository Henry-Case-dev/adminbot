# Задачи: post-deploy-admin-minors

## Атомарность и права (T-648…T-650, Epic 85 пост-деплой)

- [ ] T-648 — атомарный POST /api/config: проверить все items (типы/права/категории) ДО записи; запись батчем/транзакцией; частичный успех исключить (сейчас per-item set + 422 на середине).
- [ ] T-649 — единая запись updated_by в POST /api/info (убрать двойную запись: save_text + повторный cache.set в routes.py:497-515).
- [ ] T-650 — актуализировать docstring `can_edit_param` (deps.py:206-212): keys-категория идёт через `can_view_key_value`, не param.-право.

## Унификация кастов (дом — ЗДЕСЬ, в F-5 не дублировать)

- [ ] T-651 — унифицировать касты: `_cast_to_type` (param_catalog) / `_coerce` (hot_config) / `_coerce_value` (routes) → один хелпер.
- [ ] T-652 — hot.get на cache-miss НЕ кастовать default (hot_config.py:76 сейчас `_coerce(key, _cache.get(key, default))` кастует и дефолт).

## Валидация и документирование

- [ ] T-653 — guard alan на мусорные значения из БД (валидация типов/диапазонов после hot.get для alan-интервалов).
- [ ] T-654 — документировать поведение NaN/inf (TMA_AUTH_MAX_AGE и прочие float/int параметры) в docstring каталога.

## Прод-верификация

- [ ] T-655 — верификация @DevOps на проде: SIGTERM → корректная остановка ≤10с, БЕЗ SIGKILL по TimeoutStopSec (код 84.15.5 реализован).

## Регресс

- [ ] регресс: полный pytest.
