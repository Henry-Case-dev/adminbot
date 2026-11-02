# W-AC-P0 — AntiCliche больше не стимулирует перегенерацию

- Пакет: `AC-P0` (FINAL v8 §1.1/§1.2/§4.4 + `arch/integration-decisions.md` §3)
- Ветка: `feat/ac-p0-no-retry`, база `f1219a14`
- Реализация + тесты: **`acb8cfe4`**
- Отчёт: этот файл (следующий коммит на той же ветке)
- Вне скоупа (не трогал): `plans/current_task.md`, `progress_scope.json`,
  `workflow_state.md`, `requirements-map.json`, `web/**`, деплой, Telegram.

## 1. Что изменено

### `services/negative_constraints.py` (ядро)

1. **Стиль — только наблюдение.** Ровно в одном месте наборы правил
   разделены: `STYLE_SIGNALS` (`as_ai`, `classic_genre`, `summing_up`,
   `in_conclusion`, `hope_helped`, `mirror_no_you`, `you_asked_before`) и
   `FORMAT_GUARDS` (`plain_no_tables`, `bullet_list`). `split_rule_codes()`
   относит к наблюдениям также все динамические `dyn_*` и любой неизвестный
   код (fail-safe: сюрприз не добавляет вызов LLM).
2. **Ветка клише-повтора удалена.** В цикле повторов `else` больше не
   собирает retry-сообщение, а прерывает цикл; `CLICHE_RETRY_SYSTEM_PROMPT`
   не импортируется и не используется в модуле (проверено AST-тестом).
   Повтор возможен только по причине form / numeric / metatext / format.
3. **Возврат по первому ответу**, если сработали только стилевые коды: текст
   не переписывается, `cliche_observed`/`hits` фиксируют находки.
4. **Статистика.** `stats['hits']` сохранён (коды ответа);
   добавлены всегда присутствующие `stats['anti_cliche_retries']` (всегда 0)
   и `stats['cliche_observed']` (стилевые находки, накопительно).
5. **Формат доставки — отдельный guard.** Нарушение → ≤1 повтор, причина
   `format_guard_reason='format_retry'`, ключи `format_retry`/
   `format_rejects`/`format_fallback`; ключи form/metatext/cliché не
   переиспользуются, стилевой отказ не переименовывается в format/metatext.
6. **Ранжирование кандидатов** при исчерпании бюджета больше не учитывает
   число клише — только независимые guard'ы (T-PR-NUMERIC).
7. Докстринги модуля/функции переписаны под новый контракт; бюджет
   `_MAX_RETRIES_HARD_CAP=2` сохранён.

### `services/prompt_style_blocks.py`

Добавлен `FORMAT_NO_LISTS_RETRY_TEXT` — текст форматного повтора для
`bullet_list`, собранный из **существующего** канона (`ANTI_BOT_HEADER` +
пункт `ANTI_BOT_ITEMS` о перечнях, реестр `style.anti_bot`). Новый
prompt-канон не вводился: регистрация новой константы меняет набор фабричных
текстов (SOUL-AMD.3.2) и в этот пакет не входит. Для `plain_no_tables`
используется уже зарегистрированный `FORMAT_PLAIN_TEXT_BLOCK`
(`style.format.plain_text`). `CLICHE_RETRY_SYSTEM_PROMPT` и его регистрация
(`retry.cliche`) оставлены как исторический материал, но недостижимы.

### Вызывающие (`direct_chat_service`, `factcheck_service`, `summary_generator`)

Контракт не менялся — правки не потребовались. Побочный, ожидаемый эффект:
стилевой ответ больше не помечается `fallback`, поэтому фактчек не
отбрасывает его (`if stats.get("fallback"): return None`) — это и есть
инвариант §1.1 (пассивно после ответа, без reject).

## 2. Доказательства (кандидат `acb8cfe4`)

### 2.1 RED до изменения (дерево `f1219a14`, тот же venv)

```
== BASE f1219a14 (ДО изменения) ==
style-only             calls=3 retries=2 hits=2 fallback=True prompt=CLICHE_RETRY_SYSTEM_PROMPT ac_retries_key=False
style-many             calls=3 retries=2 hits=3 fallback=True prompt=CLICHE_RETRY_SYSTEM_PROMPT ac_retries_key=False
dynamic                calls=3 retries=2 hits=1 fallback=True prompt=CLICHE_RETRY_SYSTEM_PROMPT ac_retries_key=False
format (таблицы)       calls=2 retries=1 hits=0 fallback=False prompt=CLICHE_RETRY_SYSTEM_PROMPT ac_retries_key=False
```

Стилевой ответ стоил 3 генерации и 2 повтора; форматное нарушение
маскировалось под клише (`CLICHE_RETRY_SYSTEM_PROMPT`).

### 2.2 AFTER (кандидат `acb8cfe4`)

```
== стилевые сигналы (инвариант §1.1: ровно один вызов) ==
я как ИИ отвечаю         calls=1  retries=0  ac_retries=0  fallback=False  reason=-  prompt=—
подводя итог: как ИИ,    calls=1  retries=0  ac_retries=0  fallback=False  reason=-  prompt=—
в заключение скажу       calls=1  retries=0  ac_retries=0  fallback=False  reason=-  prompt=—
нет, это ты виноват      calls=1  retries=0  ac_retries=0  fallback=False  reason=-  prompt=—
dynamic (PG-правило)     calls=1  retries=0  ac_retries=0  fallback=False  reason=-  prompt=—

== независимые guard'ы (сохраняются, своя причина) ==
format (таблицы)         calls=2  retries=1  ac_retries=0  fallback=False  reason=format_guard_reason=format_retry  prompt=FORMAT_PLAIN_TEXT_BLOCK
format (перечни)         calls=2  retries=1  ac_retries=0  fallback=False  reason=format_guard_reason=format_retry  prompt=FORMAT_NO_LISTS_RETRY_TEXT
factual/form             calls=2  retries=1  ac_retries=0  fallback=False  reason=form_guard_reason=form_guard_rejected  prompt=FORM_GUARD_RETRY_SYSTEM_PROMPT
numeric                  calls=2  retries=1  ac_retries=0  fallback=False  reason=numeric_claim_reason=numeric_claim_corrected  prompt=NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT
metatext                 calls=2  retries=1  ac_retries=0  fallback=False  reason=metatext_reason_code=metatext_test  prompt=METATEXT_RETRY_SYSTEM_PROMPT

== комбинации ==
style + numeric          calls=2  retries=1  ac_retries=0  fallback=False  reason=numeric_claim_reason=numeric_claim_corrected  prompt=NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT
style + format           calls=2  retries=1  ac_retries=0  fallback=False  reason=format_guard_reason=format_retry  prompt=FORMAT_PLAIN_TEXT_BLOCK

== неиспользуемость стилевого промпта ==
CLICHE_RETRY_SYSTEM_PROMPT в КОДЕ negative_constraints: False
```

Матрица guard'ов: factual/form → `form_guard_rejected`; numeric →
`numeric_claim_corrected`; metatext → код причины; format →
`format_retry` (свои тексты, без стилевого промпта). Комбинация стиля с
независимым guard'ом не добавляет ни одного лишнего вызова.

### 2.3 Тесты (существующий раннер проекта, `pytest`)

`tests/test_negative_constraints_round1022.py`: **60 passed** (было 26).
Новые проверки (могут падать, см. мутации):

- `TestRuleClassification`: каждый код правил — либо стиль, либо формат;
  наборы не пересекаются; `format_retry` как литерал; неизвестный код —
  наблюдение.
- `TestAntiClicheNeverRegenerates`: по одному тесту на каждый стилевой код →
  ровно 1 `generate_call`, текст не переписан, `anti_cliche_retries == 0`,
  код в `cliche_observed`/`hits`; множественные попадания и динамическое
  правило → 1 вызов; второго промпта нет вообще; стиль не попадает в ключи
  независимых guard'ов; инвариант `anti_cliche_retries == 0` на всех путях
  (чистый/стиль/формат/исчерпание/ошибка повтора).
- `TestIndependentGuardsStillFire`: формат-таблицы и формат-перечни (≤1
  повтор, `format_retry`, свой текст, фолбэк без молчаливой правки текста);
  form/numeric/metatext со своими причинами и промптами; стиль+numeric и
  стиль+format; общий bounded-бюджет ≤3 генераций.
- `TestValidatorLoop`: петля повторов на независимом guard'е (формат),
  исчерпание, ошибка генерации на повторе, scrubber, kill-switch, отсутствие
  мутации `base_messages`; AST-тест: `CLICHE_RETRY_SYSTEM_PROMPT` не
  импортируется и не загружается ни в одном выражении модуля.

Обновлены тесты, закреплявшие снятое поведение (иначе они противоречили бы
контракту владельца): `tests/test_anticliche_round1023.py` (динамические
правила — наблюдение), `tests/test_mca08_style_form.py` (точные словари
stats + стилевой кейс без повтора), `tests/test_direct_two_call_round1022.py`,
`tests/test_factcheck_two_call_round1022.py`,
`tests/test_summary_two_call_round1022.py` (петля повторов теперь на
форматном guard'е; число вызовов пересчитано).

Целевой прогон (13 файлов, включая registry/audit-тесты):
**563 passed, 4 failed** — все 4 падают и на базе `f1219a14`
(`test_mca08::test_declared_events_really_emitted_in_code`,
`test_verbilizer_response_modes_round1023::test_summary_kill_switch_off_prev_narrator`,
`test_outgoing_guard_round1022::test_every_send_point_is_registered_or_allowlisted`,
`test_summary_two_call_round1022::test_editor_then_narrator`).

Полный прогон `pytest tests` (кандидат): 82 failed / 23 errors — весь набор
сверен с базой по junit-отчётам на 105 «падких» id:
**регрессий 0** (после правки интеграционных тестов), остальные падения
воспроизводятся на `f1219a14` без моих изменений.

### 2.4 Mutation-check (мои собственные утверждения)

| Мутация | Результат |
|---|---|
| `as_ai` снова считается триггером повтора (`FORMAT_GUARDS \| {"as_ai"}`) | 6 падений: `test_style_signal_single_generate_call[as_ai]`, `test_multiple_style_hits_single_call`, `test_style_never_sends_retry_prompt`, `test_style_hit_is_not_reported_as_guard`, `test_style_plus_numeric…`, `test_style_plus_format…` |
| `FORMAT_RETRY_REASON = "form_guard_rejected"` (маскировка формата) | 4 падения: `test_format_guards_are_delivery_not_style`, `test_format_tables_retry_with_own_reason`, `test_format_bullets_retry_with_own_reason`, `test_style_plus_format_uses_format_reason` |
| `anti_cliche_retries: 0 → 1` | 15 падений (включая инвариант и точные словари stats) |
| форматный повтор берёт `FORM_GUARD_RETRY_SYSTEM_PROMPT` вместо своего текста | 2 падения: `test_format_tables_retry_with_own_reason`, `test_format_bullets_retry_with_own_reason` |

Мутации откатаны, финальное состояние — чистое (`git status` пуст после
коммита).

## 3. Что тесты НЕ доказывают

- Реальный ответ модели: проверяется детерминированный контур
  (число вызовов, выбор промпта, stats). Качество текста без клише —
  предмет пакета подсказок (следующий пакет), а не этого.
- Поведение в живом чате/на проде не проверялось (в этом пакете деплой
  запрещён).
- Событие наблюдаемости `format_retry` в `mca_events` не эмитится: причины
  видны в `stats` и в логе `[validator] guard loop exhausted … format_rejects=`.
  Проводка в журнал/UI — задача пакетов AC-API/AC-UI; добавление нового
  имени события сейчас задело бы реестр событий, который уже падает на базе
  (`test_mca08::test_declared_events_really_emitted_in_code`).

## 4. Замечания по скоупу (для Orchestrator)

- Файловый `write_scope` пакета в `slice-graph.json` не покрывает правки,
  без которых дерево не остаётся зелёным, но которые прямо следуют из §3:
  `tests/test_anticliche_round1023.py` (владелец — AC-DATA, идёт ПОСЛЕ
  AC-P0, поэтому серийно безопасно), `tests/test_mca08_style_form.py`,
  `tests/test_direct_two_call_round1022.py`,
  `tests/test_factcheck_two_call_round1022.py`,
  `tests/test_summary_two_call_round1022.py`, а также
  `services/prompt_style_blocks.py` (был в скоупе). Правки — только
  пересчёт ожиданий под новый контракт, без ослабления проверок.
- `prompt_registry.py` намеренно не тронут: новый форматный текст собран из
  уже зарегистрированного канона, чтобы не менять набор фабричных текстов.
- Прочие (не мои) падения на базе зафиксированы отдельно; к AC-P0 не
  относятся.

## 5. Приёмка по строкам карты (кандидат `acb8cfe4`)

| Требование | Доказательство |
|---|---|
| `AC-INV-01` | §2.1 vs §2.2: стиль/множественные/динамические → 1 `generate_call`; тесты `TestAntiClicheNeverRegenerates` |
| `AC-INV-02` | матрица guard'ов §2.2 + `TestIndependentGuardsStillFire`; стиль не переименован в format/metatext |
| `AC-MET-RETRIES-ZERO` | `stats['anti_cliche_retries'] == 0` во всех путях (тест + проба) |
| `AC-DOD-ZERO-RETRY` | §2.2 целиком; независимые guard'ы сохранены |
| `T-PR-NO-RETRY` | 7 стилевых кодов + несколько попаданий + динамическое правило → 1 вызов |
| `T-PR-NUMERIC` | `style + numeric` → только numeric-повтор, клише не влияет на число повторов и ранжирование |
| `T-PR-FORM` | format/form/metatext — свои причины и тексты |
| `T-PR-NO-CLICHE-PROMPT` | AST-тест + проба: промпт не используется в коде |
| `AC-BAN-RETRY-PATHS` | ветки `CLICHE_RETRY_SYSTEM_PROMPT` в цикле больше нет (`else: break`) |
| `GLOBAL-7-NO-STYLE-MEMORY-RETRY` | стиль не выдан за form/format, доказательные gates не тронуты |
