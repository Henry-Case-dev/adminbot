# Spec F4 — Пороги Парадигм / Deep Sleep + Memory Consolidation — раунд 10.21

> **Автор:** @Architect (Step 2), 18.09.2026. **Статус:** 🟢 ACCEPTED (UPD владельца после Human Gate).
> **UPD Human Gate:** сначала READ-ONLY аудит, затем действие; **принудительное снижение порога разрешено**
> (Д11=да, значения — из отчёта аудита); консолидация идемпотентна и вызывается из CLI F5 (без авто-крона);
> флаг консолидации **не вводится** (Δ=0).
> **Фича:** `paradigm-thresholds-consolidation-round1021` (T-1971…T-1979), **P1**.
> **ADR:** `ADR-1021-4.md`. **Зависит:** F1 (качество входа), F5 (CLI-группа).
> **Baseline:** HEAD `21cd54c`; pytest **6574/0**; SQLite **v12**; БД ~2M строк / ~724 МБ.

---

## 1. Проблема и цель

«Мёртвые Парадигмы»: мета-слой Deep Sleep пуст. Нужно: READ-ONLY аудит триггеров, скрипт
**Memory Consolidation** (сжатие мусорных убеждений в парадигмы **или** принудительное снижение порога),
и решение по порогам — на основе фактов, а не догадок.

---

## 2. Аудит кода

### 2.1 Реализация есть (verify-only)
- **Deep Sleep** (10.13, F3): `services/dream_worker.py` — `_run_deep_once` (~`:1520-1650`),
  `_write_paradigm` (`:1912`, `weight=0.55`, `belief_meta.type='paradigm'`), `_paradigm_dedup_keys` (`:1901`).
  Ответ модели парсит `parse_bridge_answer` (`services/dream_prompts.py:237`), канон
  `DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT` (`:154`).
- **Настройки** (`config/settings.py`):
  - `DREAM_*` (`:1140-1161`), дефолты ослаблены в 10.18 (2/10/2/8/10/60/300000).
  - `BELIEF_*` (`:1170-1178`), `BELIEF_DECAY_ENABLED` default **False**.
  - `DEEP_SLEEP_*` (`:1187-1195`): `DEEP_SLEEP_ENABLED` default **False**, `DEEP_SLEEP_TRIGGER='after_sleep'`,
    `DEEP_SLEEP_TOP_K=20`, `DEEP_SLEEP_MAX_PARADIGMS=3`, `DEEP_SLEEP_TOKENS_PER_DAY=40000`.
- **Учёт парадигм:** `services/database.py::count_paradigms` (`:3084`), `belief_type='paradigm'` (`:3121-3140`).
- **Наблюдаемость:** `services/memory_health.py::collect_metrics` (расширяемо).
- **Каталог:** `limits.deep_sleep_max_paradigms_per_run` (`param_catalog.py:1750-1753`).

### 2.2 Гипотеза причины «пусто» (проверить аудитом)
Цепочка гейтов: `DREAM_ENABLED=False` (default) → обычный сон не идёт → `after_sleep` не триггерит Deep Sleep →
парадигм 0. Дополнительно `BELIEF_DECAY_ENABLED=False`. То есть пороги, вероятно, **ни при чём** — сначала
надо доказать, где обрыв.

### 2.3 Факт-уточнения ТЗ
- ТЗ просит «добавьте скрипт переоценки» — CLI-группы `manage.py memory` **нет**; её создаёт F5, поэтому
  консолидация встраивается туда же (не отдельный скрипт).
- Таблицы `paradigms` нет: парадигмы — это `graph_facts` с `belief_meta.type='paradigm'` (ноль DDL).

---

## 3. Целевая архитектура

### 3.1 Шаг 1 — READ-ONLY аудит (T-1972)
Отчёт `plans/reports/round1021_paradigm_audit.md` (bounded-запросы, не full-scan в event loop):
1. Флаги: `flags.dream_enabled`, `flags.deep_sleep_enabled`, `flags.belief_decay_enabled` (фактические значения).
2. Прогоны: `COUNT/SUM` по `memory_dream_log` (`kind='run'|'distilled'|'skipped'|'error'`), последние даты.
3. Кандидаты: `count_paradigms` по чатам; число убеждений (`belief_meta.type='belief'`); среднее число опор.
4. Точка обрыва: есть ли успешные обычные «сны», но 0 deep-прогонов; или 0 обычных снов.

### 3.2 Шаг 2 — Memory Consolidation (T-1973, T-1974)
Идемпотентная функция (в `services/memory_maintenance.py` или `services/dream_worker.py`) с контрактом:
- `consolidate(apply=True)` → результат `{scanned, candidates, written, skipped, reasons}`; дефолт — **боевой
  прогон** (UPD: деструктив разрешён без обязательного холостого прогона). `--dry-run` — опциональная диагностика, не обязателен.
- Вход — bounded-выборка убеждений чата (`belief_meta.type='belief'`), ранжирование по числу опор.
- Выход — парадигмы через `_write_paradigm`/дедуп `_paradigm_dedup_keys`.
- **НЕ снимать капы** `TOP_K`/`MAX_PARADIGMS`/`TOKENS_PER_DAY`.
- Вызывается ТОЛЬКО из CLI F5 (`manage.py memory consolidate`), не из тика; авто-крона нет.
- Страховочная сетка (не dry-run): авто-бэкап + JSONL-архив изменённых сгенерированных строк.

### 3.3 Шаг 3 — Решение по порогам (по результатам аудита, UPD)
Ветвление (значения берутся из отчёта T-1972):
- **A.** Обрыв из-за флагов → менять пороги НЕ нужно; санкция на включение `DEEP_SLEEP_ENABLED`/`DREAM_ENABLED`.
- **B.** Обычные сны идут, но кандидатов < порогов → **принудительно снизить** `DREAM_REPEAT_THRESHOLD`/`IMPORTANCE_SUM`
  (Д11=да; PG-миграция дефолтов по прецеденту `migrate_dream_thresholds`, `services/config_migrations.py`),
  конкретные значения — из отчёта аудита.
- **C.** Кандидаты есть, но `MAX_PARADIGMS` мал → поднять кап (значение существующего лимита, Δ записи = 0).

### 3.4 Наблюдаемость (T-1978)
Расширить `memory_health.collect_metrics`: `paradigms_total`, `paradigms_last_run`, `dream_runs_7d`,
`deep_sleep_skipped_reasons`. Причины пропуска — R17-safe reason-коды.

## 4. Флаг и раскатка (UPD)

- **Флага нет.** `flags.memory_consolidation_enabled` **не вводится** (Δ каталога = 0): консолидация **CLI-only**,
  рубильник `DEEP_SLEEP_ENABLED` остаётся основным. Авто-крона нет (решение владельца).
- Раскатки 10/50/100% нет. Изменения порогов (по отчёту аудита) — безусловная идемпотентная PG-миграция дефолтов.
- Δ каталога = 0.

## 5. План тестов

1. Аудит-функции на синтетической БД (bounded, без реальных данных).
2. `consolidate(apply=True)` идемпотентен (дедуп); повторный прогон → 0 изменений; опциональный `--dry-run` — no-op.
3. Пороги: PG-миграция дефолтов (в т.ч. принудительное снижение) идемпотентна, кастом не трогает.
4. Наблюдаемость: метрики отдаются, fail-open.
5. Регрессии cognition (`test_dream_*`).

## 6. Риски и откат

- **R1 деструктивность консолидации** — дефолт боевой, но есть страховка: авто-бэкап + JSONL-архив
  изменённых сгенерированных строк + guard (F5); опциональный `--dry-run`; откат бэкапом/архивом.
- **R2 стоимость RAG** — капы не снимаем.
- **R3 БД ~2M строк** — только bounded-запросы, офлайн/CLI.
- **R4/R5 пересечение с F5** — общие файлы (`manage.py`, `config/settings.py`, `param_catalog.py`,
  `config_migrations.py`) сводить единой ступенью; миграция дефолтов идемпотентна/обратима.
- **Откат:** обратная PG-миграция порогов; данных не теряем (бэкап + JSONL-архив).

## 7. Research references

- **Sleep-time compute (Letta/Stanford):** https://arxiv.org/pdf/2504.13171 + https://www.letta.com/blog/sleep-time-compute/ —
  отдельный «sleep-time agent» асинхронно переписывает память основного агента; ключевой риск — ошибка
  фонового размышления записывается в память как «истина» (обоснование dry-run/валидаторов).
- **Auto-Dreamer (offline consolidation):** https://arxiv.org/html/2605.20616 — двухмасштабная схема:
  быстрая онлайн-запись + медленная офлайн-консолидация с provenance и правилом «замены региона»;
  консолидация — отдельный tool-using процесс, а не побочный эффект записи.
- **Mem0 memory-evaluation:** https://docs.mem0.ai/core-concepts/memory-evaluation — временная метадата и
  ADD-only архитектура; полезно для дизайна валидатора убеждений.
