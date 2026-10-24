# QUOTES-MODES — два детерминированных режима кавычек (ADDENDUM #3 §1)

Кандидат (код/тесты/UI): `0315696b` — «feat(style): deterministic quote modes A/B (ADDENDUM #3 §1)».
Этот файл доказательств привязан к нему отдельным docs-коммитом (HEAD полосы).
Источник: `plans/features/p0-corrective-factcheck-speech/source-addendum3-2026-10-24.md` §1 (строки 13–52).

## Что сделано

| Пункт ТЗ | Реализация |
|---|---|
| A «Заменять ёлочки на обычные», default ON | заводское правило `quotes.hard.factory`, `params.mode=normalize` — `services/style_policy.py:965,974` |
| A: `«`→`"`, `»`→`"`, содержимое и остальные кавычки целы | `_apply_quotation_marks` — `services/style_policy.py:1689-1730` |
| B «Удалять кавычки полностью», default OFF | та же строка с `params.mode=strip` (пресет `no_quotes`, UI) |
| B удаляет только `«`, `»`, `"`, слова остаются | `QUOTES_STRIP_CHARS` — `services/style_policy.py:970-972` |
| Взаимоисключение, оба могут быть OFF | одна настройка = одно правило; `enabled=false` = OFF; `_collapse_quotes_rules` — `services/style_policy.py:993-1016`, вызов `:1074` |
| Защита кода/JSON/URL/литералов/дословных цитат | существующий `segment`/`protected_ranges` через `_resolve_exemptions`; дюймы `5"` не кавычка — `services/style_policy.py:1673-1686` |
| Убрать семантику (ирония/цитаты/переформулирование) | удалены `_quote_positions`, `_protected_machine_quotes`, `_QUOTE_CLASS_PAIRS`, `_LETTER_RE`; причины `ironic_quotes_removed`/`quotes_require_rephrase`/`unpaired_quote*` больше не существуют |
| Без LLM/классификаторов | проход детерминированный, `repair` не вызывается (тесты `test_zero_llm_calls_on_style_violations`) |
| UI: два пункта с пояснениями | `web/index.html:7964-7995`; состояние и взаимоисключение — `web/app.js:20355-20405` |
| Заводские значения/явные выборы сохранены | factory-правило синтезируется без миграции PG (как `dash`); легаси `quotation_marks` без `mode` = `strip` (исторический смысл «без кавычек») |
| `no_quotes` без конкурирующей обработки | пресет теперь `params={"mode":"strip"}`; `_collapse_quotes_rules` оставляет ровно одно правило кавычек |
| Global + chat overrides | chat-правило того же/любого id выигрывает у global/factory (тесты `test_chat_mode_overrides_global_mode`, `test_chat_off_overrides_global_a`) |
| Подсказка Writer не врёт | A — без инструкции; B — прежняя «не используй графические кавычки» — `services/prompt_style_blocks.py:576-601,618-631` |

## До / после (реальные прогоны)

```
# A (default ON), без документов
"Ну это «гениальная» идея"      -> 'Ну это "гениальная" идея'      repaired/quotes_normalized
"Он сказал «внешние «внутренние» слова» и „другие“"
                                -> 'Он сказал "внешние "внутренние" слова" и „другие“'

# B (no_quotes preset)
"Он сказал «база это сила»"     -> "Он сказал база это сила"       repaired/quotes_removed
'Он сказал "база это сила"'     -> "Он сказал база это сила"

# OFF (явная строка enabled=false)
"Ну это «гениальная» идея и \"прямые\" кавычки" -> байт-в-байт, исходов нет

# защищённые данные (оба режима)
'Код: print("hi")'              -> байт-в-байт (pass/exempted)
'Данные: {"k": "«v»"}'          -> байт-в-байт (exempted)
'Экран 5" и ещё 7"'             -> байт-в-байт (дюймы)
```

Было (до правки, `no_quotes`): многословная цитата «база это сила» не менялась и давала
`conflict/quotes_require_rephrase` — то есть семантическое решение вместо детерминированного.

## Тесты

- `tests/test_quotes_modes.py` — 29 проверок (CONTRACT owner=QUOTES-MODES/A-B): A/B/OFF,
  вложенные, код/JSON/URL/литералы, взаимоисключение, `no_quotes` без двойной обработки,
  рестарт (save → reload global и chat), UI-контракт двух пунктов.
- Обновлены под новый контракт: `tests/test_soul1_style_policy.py` (5 кавычковых тестов,
  factory-ids, bounded repair через `line_breaks`), `tests/test_soul1_style_payload.py`
  (payload-конфликт через `line_breaks`; инициативный текст сохраняет слова),
  `tests/test_soul1_style_repetition.py` (повтор не срезан, типографика — отдельное правило).
- Прогон: `py -3 -m pytest tests/test_quotes_modes.py tests/test_soul1_style_policy.py
  tests/test_soul1_style_payload.py tests/test_asap3_style_hint_limits.py` → **116 passed**.

## UI-проверка (реальный рендер)

- Playwright (`OPENCODE_WORKFLOW_SCRATCH/quotes-modes-ui/probe.py`, стабы `/api/*`):
  390×844 и 1280×900 — 0 провалов; default A=ON/B=OFF; клик B снимает A; клик A снимает B;
  повторный клик A → «Оба режима выключены»; Save отправляет ровно одно правило
  `quotation_marks` с `params.mode=normalize`, `enabled=true`; тач-цели ≥44px; overflow ≤1.
- Browser Use (реальная страница `http://127.0.0.1:8879/#/ai/speech`): чекбоксы и тексты
  отрисованы, взаимоисключение подтверждено кликом (B=on → A=off).
  Скриншоты: `OPENCODE_WORKFLOW_SCRATCH/quotes-modes-ui/shots/`.

## Риски / границы

1. A включён по умолчанию для всех чатов: исходящий текст с ёлочками теперь меняется на
   прямые кавычки (это и есть требование). Отключение — явной строкой `enabled=false`.
2. Режимы не трогают `„“ “” '` (в ТЗ перечислены только `« » "`), поэтому «умные» кавычки
   остаются как есть — осознанно узкий, предсказуемый набор.
3. `strip` не схлопывает пробелы вокруг удалённых кавычек (`« база »` → ` база `): содержимое
   сохраняется байт-в-байт, косметика пробелов — не задача этого правила.
4. Семантические исходы кавычек (`conflict`/`denied` для обычного текста) больше не
   возникают; стратегии конфликта остались для защищённого текста и других правил.
