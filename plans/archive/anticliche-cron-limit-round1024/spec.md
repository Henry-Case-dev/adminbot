# spec.md — F7 `anticliche-cron-limit-round1024` (лимит 200 + фикс крона)

> Раунд 10.24, Часть 1 (backend-core) · Приоритет **P1** · ADR: **ADR-1024-3** (AMEND ADR-1023-4 D2)
> ТЗ: `plans/current_task.md` UPD2 п.5 (стр. 188–193), UPD3 п.3 (стр. 248–249). Секреты не цитировать (R17/R18).
> Baseline: HEAD `00eab85`; pytest 7424/0; каталог 457/96/94; SQLite v12.

## 1. Цель

1. Снять хардкод-лимит 20: парсер забирает все выявленные клише в пределах **защитного максимума**, дефолт **200**, параметр **регулируемый** (числовое поле в UI, ключ каталога).
2. Починить крон: первый прогон **вскоре после деплоя**, далее недельный интервал; причина любого сбоя видна в логах.

## 2. Что уже есть (координаты)

- Лимит: `services/anticliche_cache.py:26` (`ANTICLICHE_MAX_PATTERNS=20`), применение `:94`; `services/anticliche_worker.py:117` (`build_patterns(max_patterns=ANTICLICHE_MAX_PATTERNS)`), `:142-143`, `:321` (`EXTRACT_SYSTEM_PROMPT.format(max=…)`); API `web/api/anticliche.py:79`.
- Крон: `services/anticliche_worker.py:183-202` (`start`, `IntervalTrigger(days=7, jitter=3600)`), `tick` `:217-227`; регистрация `bot.py:666-693`.
- Кэш-метаданные: `anticliche_cache.fetch_cache` возвращает `fetched_at`/`updated_at`/`version`/`last_status` (`services/anticliche_cache.py:119-140`).
- UI: `web/index.html:375-397` (`паттернов: count / max_patterns`, кнопка «Обновить сейчас»).
- Лог-хуки: F2 `services/external_log.py` (ADR-1024-1).
- Флаг: `DYNAMIC_ANTICLICHE_ENABLED` (env-only, default ON).

## 3. Требуемое поведение

1. Эффективный лимит = `max_patterns()` (clamp `[1, 1000]`), резолв `hot → settings.ANTICLICHE_MAX_PATTERNS` (default **200**).
2. Парсер/дедуп/промпт используют резолвленное значение; API отдаёт резолвленное `max_patterns`.
3. Джоб регистрируется с `next_run_time = now + ANTICLICHE_FIRST_RUN_DELAY_MINUTES` (5 мин) и далее `IntervalTrigger(days=7, jitter=3600)`.
4. `tick(force=False)` пропускает refresh, если `fetched_at` свежее 7 дней (`skip reason=fresh`); ручной форс — `force=True`.
5. Логи: `next_run_time` при старте; при сбое — фаза (`fetch|llm|parse|empty|write`), `exc_info`, число полученных/сохранённых.
6. UI-подпись/поле отражают резолвленный лимит; монитор консистентен с API.

## 4. Изменения по файлам

| Файл | Изменение |
|---|---|
| `services/anticliche_cache.py` | `ANTICLICHE_MAX_PATTERNS_DEFAULT=200`, `ANTICLICHE_MAX_PATTERNS_HARD_CEILING=1000`, `max_patterns()`; `_rules_from_patterns` читает `max_patterns()`; deprecated-alias сохранить |
| `services/anticliche_worker.py` | `build_patterns(max_patterns=None→resolved)`, `_call_llm` → `format(max=max_patterns())`; `start()` → `next_run_time`; `tick` → freshness-skip + лог фаз (F2); `refresh(force=False)` |
| `services/param_catalog.py` | +группа `limits_anticliche`, +ключ `ANTICLICHE_MAX_PATTERNS` (group `limits_anticliche`); `TAB_RULES[TAB_PROMPTS]` += limits-группа |
| `config/settings.py` | `ANTICLICHE_MAX_PATTERNS: int = _env_int(...200...)`; env-only `ANTICLICHE_FIRST_RUN_DELAY_MINUTES=5` |
| `web/api/anticliche.py` | `max_patterns` = `anticliche_cache.max_patterns()` |
| `web/index.html` / `web/app.js` | (Часть 2, web-очередь) числовое поле лимита в карточке анти-клише + консистентный счётчик |

## 5. Контракты

```python
# services/anticliche_cache.py
ANTICLICHE_MAX_PATTERNS_DEFAULT = 200
ANTICLICHE_MAX_PATTERNS_HARD_CEILING = 1000
def max_patterns() -> int: ...   # hot.get("limits.anticliche_max_patterns", settings.ANTICLICHE_MAX_PATTERNS), clamp [1, ceiling]
```

- Ключ каталога: `limits.anticliche_max_patterns` (int, default 200, group `limits_anticliche`).
- `refresh(force=False)`: `force=True` игнорирует freshness-skip.
- `start()`: `add_job(..., next_run_time=datetime.now(tz) + timedelta(minutes=DELAY), trigger=IntervalTrigger(days=7, jitter=3600), max_instances=1, coalesce=True, misfire_grace_time=3600)`.

## 6. Тесты

- (a) парсер возвращает >20 при источнике >20 (default 200).
- (b) hard-ceiling применяется; clamp на 0/отрицательных/мусоре → ≥1.
- (c) крон: первый прогон запланирован вскоре после старта, далее интервал (mock scheduler — проверить `next_run_time`/trigger).
- (d) `tick` при свежем `fetched_at` → `skip reason=fresh`, без LLM-вызова.
- (e) ошибка источника не роняет `tick`; в логе — фаза/причина.
- (f) API отдаёт резолвленный `max_patterns`.
- (g) пин-тесты каталога (`test_param_catalog`, `test_frontend_tab_mapping`) обновлены.

## 7. Флаги / Δ

- `DYNAMIC_ANTICLICHE_ENABLED` (есть, ON); `ANTICLICHE_FIRST_RUN_DELAY_MINUTES` (env-only, 5).
- Δ каталога: **+1 ключ, +1 группа** → REGISTRY 457→458, GROUPS 96→97, `_TAB_BY_GROUP` 94→95.
- Δ DDL = 0.

## 8. Риски

- **R1 (High):** длинный список раздувает детектор/стоимость → hard-ceiling 1000 + дедуп/нормализация.
- **R2 (High):** старт сразу после деплоя даёт лишний LLM-вызов → freshness-skip + guarded delay + таймаут.
- **R3 (Medium):** ложные срабатывания детектора при расширении → сохраняется валидатор/ручная правка (`apply_manual`).
- **R4 (Low):** `next_run_time` не переживает рестарт как объект → покрыто freshness-skip (окно не сдвигается).
- **R5 (R17/R18):** ключи/фразы не в логах.

## 9. Критерии приёмки

- Искусственный лимит 20 снят; default 200; парсер сохраняет все клише источника в пределах hard-ceiling.
- Фоновый крон отрабатывает самостоятельно, включая первый прогон после деплоя.
- В логах видна причина любого сбоя крона; `next_run_time` залогирован.
- UI-подпись/поле соответствуют реальным данным. Каталоговые пин-тесты зелёные.

## 10. Откат

- Вернуть прежний лимит/поведение (флаг OFF / смена hot-значения) / `git revert`. Δ DDL = 0.

## 11. Артефакты-ссылки

- ADR: `ADR-1024-3.md`; AMEND `plans/archive/dynamic-anticliche-cache-round1023/ADR-1023-4.md`;
- карта: `round1024-architecture.md` §3.3, §5.
