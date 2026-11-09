# NOST-PROACTIVE — привязка доказательств к выкладке 2.58.178

Дата привязки: 10.11.2026 (PM).
Карта: `plans/features/smart-module-semantic-routing/requirements-map-nostalgia-correction.json`.
Граф: `plans/features/smart-module-semantic-routing/slice-graph.json`, срез `NOST-PROACTIVE`.

## 1. Идентификация выкладки

| Поле | Значение |
|---|---|
| Версия | 2.58.178 |
| Кандидат/выкладка (этот срез) | `af84b6c68ae253d2f593df4123ff3ca7b72fe65d` |
| Ветка | `release/2.58.178` |
| Предыдущая выкладка | `1a4a9b1b1ba7429d54f8ca651ce9629efcda7f8e` (2.58.177, P1) |
| Схема БД | 46, без изменений, DDL не выполнялся (`services/database.py` вне diff) |
| Коммиты среза | `1e5e57ba` (реализация), `f4bc2594` (устранение ревью-блокеров), `af84b6c6` (release-пины) |
| Артефакт выкладки (другая ветка) | `release/2.58.178:plans/features/smart-module-semantic-routing/evidence/nost-pro-01-release-2.58.178.md` @ `dc79e5e4` |

**Политика отдельных кандидатов на срез.** SHA `af84b6c6…` относится только к срезу `NOST-PROACTIVE`.
Доказательства `SMR` P0/P1 (`2.58.176`/`2.58.177`, кандидат `1a4a9b1b`) этой выкладкой **не** объявляются
байт-идентичными: P0/P1 привязаны к своим кандидатам и своим версиям, а здесь проверялся только дельта-набор
файлов ностальгии (см. §2).

## 2. Дельта 1a4a9b1b → af84b6c6 (проверено в этом шаге)

Команда: `git diff --name-status --ignore-cr-at-eol 1a4a9b1b af84b6c6` → **35 файлов**, из них содержательные:

- продукт/конфиг: `services/nostalgia_worker.py`, `services/initiative_observer.py`, `services/prompt_registry.py`, `config/settings.py` (только `APP_VERSION` и release-примечание), `plans/docs/param-registry-round1025.meta.md` (F8 meta);
- тесты: `tests/test_nostalgia_proactive_recall.py` (**новый**, 514 строк, 9 тестов), правки в `tests/test_nostalgia_worker.py`, `tests/test_p0_followup_nostalgia_ab.py`, `tests/test_p0_prompts_core.py`, `tests/test_expression_isolation_followup.py`, `tests/test_mca10b_random_applications_block_a_round1041.py`;
- остальные 26 файлов — однострочные version/пины.

Отсутствуют в дельте (то есть не менялись): `services/direct_chat_service.py`, `services/direct_capabilities.py`,
`services/direct_l1.py`, `services/direct_execution.py`, `handlers/`, `web/`, `services/database.py`.

Оговорка по шуму diff: `git diff --stat 1a4a9b1b af84b6c6` без `--ignore-cr-at-eol` показывает ~18k вставок из-за
нормализации переводов строк (CRLF/LF). Семантическая дельта — перечисленные 35 файлов; большие числа в «сыром»
diff не являются продуктовыми изменениями.

## 3. Промпт-пины (проверено в этом шаге по diff `services/prompt_registry.py`)

- Изменён **ровно один** блок из 112 — `internal.initiative_observer` (`services.initiative_observer.OBSERVER_EVAL_SYSTEM_PROMPT`,
  `internal`/`code`, `ui=code_only`, внутренний машинный промпт, не пользовательская персона).
- Печать блока: `f1169884093b` → `108f277a466f`; метка редакции `initiative-observer` → `initiative-observer-memory-recall`.
- Отпечаток набора фабричных текстов: `b4e8b3569ab2` → `011c83dfac95`; прежнее значение сохранено в истории комментариев.
- Указатель потребителя: `initiative_observer.py:895` → `initiative_observer.py:944`.
- Остальные 111 канонов и все 12 legacy-персон — байт-в-байт; пользовательские тексты промптов не менялись.

Косметическое замечание (не блокер): в комментарии к `FACTORY_SET_SHA256_12` написано «Прочие 110 канонов»,
тогда как при 1 изменённом из 112 остальных — 111. Расхождение только в тексте комментария, поведение пинов
проверяется тестами.

## 4. Рантайм-факты (in-process, по отчёту Builder/DevOps за 2.58.178)

- `nostalgia_tick` зарегистрирован (`IntervalTrigger` 60 мин, `max_instances=1`, `coalesce=True`), воркер запущен при включённом флаге;
- шов `recall_in_conversation(chat_id, *, now=None, memory_refs=(), context_rows=None) -> dict` существует и на сфабрикованных ссылках возвращает `{"status": "skipped", "reason_code": "no_relevant_memory"}` при нуле отправок и нуле LLM-вызовов;
- маршрут Observer `kind == "memory_recall"` подтверждён (`_act_on_memory_recall`, `memory_slot`, счётчики `memory_recall_sent/silent/unavailable/error`);
- пре-гейт `DIG_PRE_GATE_ENABLED` без потребителей в `services` (единственное упоминание — метаданные `services/param_catalog.py`), эффективно выключен;
- канон чекапа v10; фабричный отпечаток на работающей сборке равен `011c83dfac95`.

## 5. Прогоны тестов на дереве релиза (по отчёту за 2.58.178)

55 nostalgia core; 241 nostalgia+mca09; 228 passed / 4 failed observer-initiative; 1194 passed / 1 failed
memory-experience; 145 random; 805 passed + 2 skip / 3 failed prompts-registry. Все 8 падений воспроизводятся
на `1a4a9b1b` (то есть не внесены этим срезом). Ранее падавший `TestHotEnable` теперь проходит.

## 6. Прод-проверки (по отчёту DevOps за 2.58.178)

2.58.178 отдаётся публично, `NRestarts 0`, в логах нет traceback/ERROR, одно предупреждение — ранее существовавшее,
схема 46. Живые настройки: `memory.nostalgia_enabled=true`, `layer_a=true`, тик 60 мин, тишина 45 мин, 3/день,
тихие часы 23–8; чатовых OFF-переопределений нет.

## 7. Привязка по строкам

VERIFIED (11): NOST-PRO-02, -03, -04, -05, -06, -08, -09, -10, -11, -18, -19.
PENDING с частично привязанным доказательством (2): NOST-PRO-01, NOST-PRO-12.
PENDING без доказательств (6): NOST-PRO-07, -13, -14, -15, -16, -17.

Обоснование границы: строки, чья приёмка сформулирована как наблюдаемое поведение **в живом чате** (01, 14, 15, 16, 17),
остаются PENDING до реальных сценариев в Telegram, даже при наличии зелёных unit-тестов. Строки о механизме,
отсутствии дублирования, пинах промптов и эффективном состоянии флагов привязаны к выкладке.

## 8. Что переоткроется квантовой корректировкой

Корректировка `OI-2026-11-10-QUANTUM-NONDETERMINISM` (полная недетерминированность вместо QRNG-только-тай-брейк:
пер-чатовое расписание, пробуждение по событию, вероятность публикации) изменит этот срез повторно:
расписание тика (NOST-PRO-03, -19), точку пробуждения/шов (NOST-PRO-02, -05), выбор кандидатов и RandomSource
(NOST-PRO-07, -08, -12, -13). Эти строки будут переоформлены отдельным добавлением в карту; текущая привязка
фиксирует состояние 2.58.178 и не отменяет будущих правок.

## 9. Остаток до полного VERIFIED среза

1. Живые сценарии в реальном чате: 14 (спонтанное воспоминание в дискуссии), 15 (автономная инициатива), 16 (вопрос о прошлом без ключевых слов).
2. Живая проверка источников: 17 (реальные записи памяти, отсутствие выдуманных связей и повторов).
3. Поведенческое подтверждение смыслового обнаружения связи в живом диалоге: 01.
4. Квантовая часть отбора: 07, 12, 13 (после корректировки недетерминированности).
