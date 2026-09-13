# Спека F3 — `sleep-unblock-diagnostics-round1015` (Разблокировка Сна + пре-гейт диагностика)

> **Статус:** ✅ COMPLETED (Step 4 @Builder, 14.09.2026). Реализация T-1567…T-1573 завершена; pytest **5761 passed / 0 failed**.
> **Раунд:** 10.15. **Тип:** backend (`services/dream_worker.py`). **Приоритет:** P0 (блокер синтеза убеждений). **T-ID:** T-1566…T-1574.
> **ТЗ:** `plans/current_task.md` §2. **Зависимости:** нет. **Конфликт файлов:** `services/dream_worker.py`; `web/api/memory_agi.py` — не трогаем (аддитивных полей не требуется).
> **Baseline:** HEAD `798e044`; pytest 5589/0; каталог 435/406/411/90/88/19.

## 1. Цель

Разблокировать синтез: если за последние 3 дня **не синтезировано ни одного убеждения** — динамически снижать пороги гейта до `min_cluster_size=2` / `min_importance_sum=8`. Плюс обязательный пре-гейт-лог с причинами отказа, **видимый в панели «Логи»** (раздел Статус).

**Проблема сейчас:** гейт `services/dream_worker.py:485-514` (`repeat_min`/`sum_min`) отбрасывает все кластеры; текущий лог `[dream] no qualifying clusters facts=%d` (`:510-512`) не даёт понять причину; панель «Логи» по умолчанию фильтрует `ERROR+WARNING` (`services/log_ring.py:139-162`, `get_entries('ERROR+WARNING')` = WARNING ∪ ERROR ∪ CRITICAL) → **INFO-лог не виден**.

## 2. Scope

**In scope**
- Детект «0 убеждений за 3 дня» (глобально) через существующий хелпер.
- Динамическое применение fallback-порогов 2/8 в гейте.
- Пре-гейт-лог ровно заданного формата (skipped + passed), skipped — на WARNING.
- Unit-тесты fallback и формата лога.

**Out of scope**
- Новые каталог-ключи (Δ=0). Новые таблицы/колонки. Изменение базовых ключей `memory.dream_repeat_threshold`/`memory.dream_importance_sum_threshold`.
- Изменения `web/api/memory_agi.py` (статус сна не расширяем — см. F5).

## 3. Детект «0 убеждений за 3 дня»

F3-Q1 RESOLVED: источник — `memory_dream_log` (**не** таблица beliefs, чтобы не зависеть от статуса/архивации).

Использовать существующий хелпер `services/database.py:3579-3594`:
```python
last = await self.db.last_run_at(("distilled",), chat_id=None)   # глобально
now_ts = now
fallback_active = (last is None) or (last < now_ts - 3 * 86400)
```
- `last_run_at(kinds, chat_id=None)` уже возвращает `MAX(run_at)` по `kind IN ('distilled')` глобально.
- **F3-Q3 RESOLVED: детекция глобальная**, применение — к гейту каждого чата. Обоснование: ТЗ описывает системную проблему («сон не синтезирует несколько дней»); per-chat детект давал бы «трэш» в тихих чатах, где чужие убеждения есть. Глобальное «оживление» снимает блокировку сразу.
- **F3-Q2 RESOLVED: fallback-значения — код-константы** в `services/dream_worker.py` (каталог-Δ=0):
  ```python
  _FALLBACK_WINDOW_DAYS = 3
  _FALLBACK_MIN_CLUSTER_SIZE = 2
  _FALLBACK_MIN_IMPORTANCE_SUM = 8
  ```
- **F3-Q4 RESOLVED: отдельный kill-switch не вводим** — fallback самоотключается при первом же синтезированном убеждении (self-healing), риск ограничен; откат = `git revert`. (Минимизация каталога.)

## 4. Применение порогов (точный алгоритм)

В `_distill_chat` (`services/dream_worker.py:491-506`):

```python
repeat_min = int(self._key("repeat_threshold",
                           settings.DREAM_REPEAT_THRESHOLD) or 3)
sum_min = int(self._key("importance_sum_threshold",
                        settings.DREAM_IMPORTANCE_SUM_THRESHOLD) or 12)
fallback_active = await self._sleep_fallback_active(now)   # см. §3
if fallback_active:
    repeat_min = _FALLBACK_MIN_CLUSTER_SIZE          # 2
    sum_min = _FALLBACK_MIN_IMPORTANCE_SUM           # 8
qualified = [cl for cl in clusters
             if len(cl) >= repeat_min
             and sum(int(r["importance"] or 0) for r in cl) >= sum_min]
```
- **Не ломать обычные пороги:** fallback применяется ТОЛЬКО при `fallback_active`; иначе — базовые значения из `memory.dream_*` (или settings-дефолт).
- **Возврат к базовым:** как только `last_run_at(("distilled",))` свежее 3 дней — `fallback_active=False`.
- **Защита от мусора:** fallback всё равно требует `len(cluster) >= 2` И `sum >= 8` (единичный факт не пройдёт).
- `self._sleep_fallback_active(now)` — новый приватный async-метод (fail-safe: ошибка БД → `False`, базовые пороги).

## 5. Формат пре-гейт-лога (ровно по ТЗ)

F3-Q5 RESOLVED: `threshold` = **эффективный порог суммы важности** (`sum_min`, соответствует «Max importance»); размер-порог отдельно не печатаем (формат ТЗ фиксирован).

Формат (байт-в-байт шаблон, `%d`-подстановки):
```python
# ссылка на `[Sleep]` — точный grep-маркер
logger.warning(
    "[Sleep] Chunks: %d, Clusters formed: %d, Max importance: %d "
    "-> Skipped (threshold %d)",
    len(rows), len(clusters), max_importance, sum_min)
logger.info(
    "[Sleep] Chunks: %d, Clusters formed: %d, Max importance: %d "
    "-> Passed (threshold %d)",
    len(rows), len(clusters), max_importance, sum_min)
```
где:
- `Chunks` = `len(rows)` — число фактов, поданных в кластеризацию (после protected-фильтра);
- `Clusters formed` = `len(clusters)` — всего кластеров (до гейта);
- `Max importance` = `max(sum(int(r["importance"] or 0) for r in cl) for cl in clusters)` при непустых кластерах, иначе `0`;
- `threshold` = эффективный `sum_min` (2 в fallback / 12 базовый).

**Решение по уровню (ключевое):**
- **`-> Skipped` логируется на уровне `WARNING`** — только этот уровень гарантированно виден в дефолтном фильтре «Логи» (`ERROR+WARNING`). Спам ограничен: при отказе вызывается `_finish_chat(chat_id, now, rows)` (`:513`), все факты помечаются обработанными → строка `[Sleep]` для этого чата не повторяется, пока не появятся новые факты.
- **`-> Passed` логируется на уровне `INFO`** — не засоряет дефолтный фильтр; факт синтеза виден в Timeline/stats.
- **R17:** только числа, без текстов фактов/имён/ключей.
- Старый лог `[dream] no qualifying clusters facts=%d` (`:510-512`) **заменяется** новой строкой (не дублировать).

## 6. Точки изменения (file:line, HEAD `798e044`)

| # | Файл:строка | Изменение |
|---|---|---|
| 1 | `services/dream_worker.py:485-514` | Гейт: вычисление `fallback_active`, подмена `repeat_min`/`sum_min`, новый `[Sleep]`-лог (skipped/passed), удаление старого лога `:510-512`. |
| 2 | `services/dream_worker.py` (модуль, рядом с константами) | Новые код-константы `_FALLBACK_WINDOW_DAYS/_FALLBACK_MIN_CLUSTER_SIZE/_FALLBACK_MIN_IMPORTANCE_SUM`. |
| 3 | `services/dream_worker.py` (метод класса) | Новый `async def _sleep_fallback_active(self, now) -> bool` (через `self.db.last_run_at(("distilled",))`, fail-safe). |
| 4 | `services/database.py:3579-3594` | **Не менять** — хелпер `last_run_at` переиспользуется как есть. |

**Не трогать:** `config/settings.py:1101-1103` (базовые дефолты), `services/param_catalog.py:1414/1419`, `services/log_ring.py`, `web/api/memory_agi.py`.

## 7. Feature-флаг / progressive delivery

- **Feature flag:** не вводится (каталог-Δ=0). Fallback самоотключается при появлении убеждения; базовые пороги настраиваются существующими `memory.dream_repeat_threshold`/`memory.dream_importance_sum_threshold`. Откат = `git revert`.
- **Progressive delivery:** неприменимо.

## 8. Тест-план

Новый `tests/test_sleep_fallback_round1015.py` (+ расширить `tests/test_dream_worker.py`):
1. **Активация:** `last_run_at(distilled) == None` или старше 3 дней → `fallback_active=True`, кластер с 2 фактами/Σ8 проходит в fallback.
2. **НЕ-активация:** свежее убеждение (< 3 дней) → базовые 3/12; кластер 2/Σ8 отброшен.
3. **Возврат:** после синтеза убеждения (`last_run_at` свежий) fallback выключается.
4. **Защита:** одиночный факт (кластер 1) не проходит даже в fallback.
5. **Формат лога (skipped):** точная строка `[Sleep] Chunks: 15, Clusters formed: 2, Max importance: 9 -> Skipped (threshold 12)` (caplog, level WARNING).
6. **Формат лога (passed):** строка `-> Passed (threshold 12)` (level INFO) при попадании в топ.
7. **Видимость в «Логи»:** unit `log_ring.get_entries('ERROR+WARNING')` содержит запись `[Sleep]` (WARNING).
8. **Регресс:** при свежих убеждениях обычное `[dream]`-поведение не сломано; `_finish_chat` вызывается при skip.

**Гейты:** полный `pytest` 0 failed; каталог Δ=0; R17-скан (в логе только числа); `git diff --check`; русский conventional commit.

## 9. Риски

| Риск | Митигация |
|---|---|
| Ложные синтезы из слабых кластеров в fallback | Порог 2/8 + только при глобальном «0 убеждений 3 дня»; ревью качества T-1574. |
| Спам WARNING в «Логах» | `_finish_chat` помечает факты обработанными → строка не повторяется до новых фактов. |
| Дорогой `last_run_at` каждый чат | Один дешёвый `MAX(run_at)` по индексу; вычислять **один раз на тик** и кэшировать в локальной переменной `_run`. |
| Ошибка БД в детекте | fail-safe → `False` (базовые пороги). |

## 10. Критерии приёмки (DoD)

- [ ] Fallback срабатывает ровно при «0 убеждений за 3 дня» → пороги 2/8; иначе базовые 3/12; возврат автоматический.
- [ ] В «Логах» виден `[Sleep]`-пре-гейт с chunks/clusters/max importance/threshold (skipped — WARNING; passed — INFO).
- [ ] Диагностика за один взгляд объясняет, почему LLM не вызывался (расход 0 токенов).
- [ ] Полный `pytest` 0 failed; каталог-инварианты 435/406/411/90/88/19 не нарушены.

## 11. Инварианты

Формат лога ровно по ТЗ (grep-safe), R17 (без секретов/фактов), SQLite-схема без изменений, записи только существующими методами, `media/`/`.env`/порядок роутеров `bot.py` не трогать.
