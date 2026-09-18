# spec.md — F6 `telegram-send-regex-guard-round1022`

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 2b @Architect · Тип: канон промптов + backend `services/**`
> **ADR:** `ADR-1022-6.md` (**Accepted — UPD3 §3: вето на `string.replace`, validator-loop**). **Задачи:** `tasks.md` (T-2062…T-2069 + T-2092/T-2093).
> **ТЗ:** `plans/current_task.md`, UPD3 §3 (строки **259–262**) + «ЧАСТЬ 1 → 4» (215–218).
> **Роль изменилась:** F6 — **не «вырезать клише»**, а **детектор клише + петля возврата**; regex тихо режет **только технические теги**.
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**.

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| Единая точка среза reasoning-тегов | `services/reply_postprocess.py:39-74` (`strip_reasoning_tags`) |
| cleanup саммари | `services/summary_cleanup.py:20-30` (`cleanup_llm_text` → strip) |
| Negative constraints | `services/prompt_style_blocks.py:21-27` (`ANTI_BOT_BLOCK`), `:30-34` (`ASYMMETRY_BLOCK`), `:37` (`STYLE_BLOCKS_SUFFIX`) |
| Список тегов-черновиков | `reply_postprocess.py:28-30` (`reasoning/thinking/scratchpad/analysis/thought`) |
| Точки `bot.send_message` | **19** в 10 файлах: `handlers/{summary,slava_presence,video_download}.py`, `services/{dead_page_relay,media_send,mimic_relay,nostalgia_worker,smartmodule_utils,progress_reporter,summary_generator}.py` |
| Ре-экспорт/идемпотентность | `strip_reasoning_tags` вызывается в direct (`:758`), tool-loop (`:124,139,175`), factcheck (`:128`), summary (`:241`) |

### 0.1. Чего нет сейчас

- Нет вырезания `fact:\d+` / `msg:\d+`.
- Нет **единого chokepoint** отправки: каждая точка вызывает `bot.send_message` напрямую.
- Нет **детектора ИИ-клише** и механизма «брак → возврат Вербализатору».

### 0.2. Вето владельца и новая роль (критично)

`string.replace` для клише («Я как ИИ», «Надеюсь, помог») **ЗАПРЕЩЁН**: хардкод-вырезание
ломает грамматику и оставляет «дыры» в предложениях. Поэтому:
- **Regex Scrubber** — тихо и детерминированно режет **только технические теги**
  (`<thought>`-семейство и `fact:\d+`/`msg:\d+`); **клише он не трогает**.
- **Validator Loop** — Python-сканер находит запрещённое клише и **бракует весь ответ**,
  возвращая его в LLM-Вербализатор (**max 2 ретрая**) с системным сообщением-negative-constraint.

### 0.3. Инварианты/ограничения

- Не дублировать стрип: chokepoint — единственная новая точка гарантии; существующие вызовы
  `strip_reasoning_tags` идемпотентны и остаются (нулевой регресс).
- Regex не должен резать легитимный текст: якорные границы слов; латинские префиксы
  `fact:`/`msg:`; кириллическое «факт»/«сообщение» не матчатся.
- `parse_mode=HTML`: Telegram **не поддерживает** `<thought>`/`<reasoning>` — стрип обязателен
  **до** отправки.
- **Детектор клише живёт в обычном коде, а НЕ в prompt-константах** (`prompt_style_blocks.py`) —
  иначе grep-тест отсутствия тропов поймает сам список клише (прецедент F3/10.21).
- R17: в логах — только длины/числа/коды, без содержимого и без самих совпавших строк.

---

## 1. Цель

(а) Расширить negative constraints против RLHF-клише (стиль рубленый/непредсказуемый).
(б) Ввести **единый egress-предохранитель**: regex тихо режет `<thought>`-семейство и
`fact:\d+`/`msg:\d+`.
(в) Ввести **Validator Loop**: детектор запрещённых клише → браковка ответа → возврат
Вербализатору (≤2 ретрая) → детерминированная деградация.

## 2. Архитектура

### 2.1. Regex Scrubber — модуль `services/outgoing_guard.py` (новый)

Единственная чистая функция (без I/O, без БД):

```
sanitize_outgoing(text: str, *, parse_mode: str | None = None) -> str
  1) strip_reasoning_tags(text)                 # reuse reply_postprocess (идемпотентно)
  2) _ID_RE.sub("", ...)  для \bfact:\d+\b и \bmsg:\d+\b (регистронезависимо, латиница)
  3) no-op, если паттернов нет — байт-в-байт
  4) нормализация пробелов ТОЛЬКО вокруг вырезанного фрагмента
```

- **Клише НЕ вырезаются** (вето, §0.2).
- **Fail-closed:** неожиданная ошибка → вернуть `""` (не отправлять сырьё) + WARNING (длины).
- **Идемпотентность:** повторный вызов не меняет результат.
- Расширяемость `EXTRA_PATTERNS`; сегодня — только `fact`/`msg`.

### 2.2. Обёртки отправки `services/telegram_send.py` (новый)

- `async def send_text(bot, chat_id, text, **kw)` → `sanitize_outgoing` → `bot.send_message`.
- `async def edit_text_safe(msg, text, **kw)` → `sanitize_outgoing` → `msg.edit_text`.
- `async def send_caption(bot, chat_id, media, caption, **kw)` → guard на `caption`.
- **Реестр `SEND_POINTS`** (файл → функция); все найденные точки мигрируют на обёртки; тест покрытия.

### 2.3. Детектор клише + Validator Loop — `services/negative_constraints.py` (новый)

**Публичный API:**

```python
FORBIDDEN_CLICHE_PATTERNS: tuple[ClicheRule, ...]     # код/регекс (в коде, не в промпте)
def find_forbidden_cliches(text: str) -> list[str]    # возвращает КОДЫ (R17), fail-open
async def verbalize_validated(generate_call, base_messages, *,
        max_retries: int = 2, scrubber=sanitize_outgoing) -> tuple[str, dict]
```

**Финализированный список клише (объединение 10.21 + UPD2) и detection-правила:**

| Код | Что ловим (регистронезависимо, word-boundary, unicode) |
|---|---|
| `as_ai` | «как ИИ», «я как ИИ», «я — ИИ», «я искусственный интеллект», «как языковая модель», «языковая модель» |
| `classic_genre` | «классика жанра» |
| `summing_up` | «подводя итог», «подводя итоги» |
| `in_conclusion` | «в заключение», «в завершение» |
| `hope_helped` | «надеюсь, помог», «надеюсь, это помогло», «надеюсь, я помог», «надеюсь, было полезно» |
| `you_asked_before` | «ты уже спрашивал», «ты уже спрашивала», «вы уже спрашивали», «ты спрашивал это», «уже спрашивал это» |
| `mirror_no_you` | «нет, ты», «нет, это ты» — зеркальные перепалки (регекс `\bнет\b[,\s]+(?:это\s+)?ты\b`) |
| `bullet_list`* | строка-буллит/нумерация (`^\s*[-*•]\s+` / `^\s*\d+[.)]\s+`) — только там, где канон требует plain-text без списков (F3/F4/F5) |

\* `bullet_list` — **вторичное** правило (передаётся `enabled_rules`), чтобы не ловить ложные
срабатывания в текстах, где списки допустимы.

- **Нормализация:** lower-case, схлопывание пробелов/дефисов; `ё→е`; сравнение по `re.search`
  с `\b`-границами. Правила — компилированные `re.Pattern` (детерминированно, без LLM).
- **Fail-open:** ошибка детектора → считать текст чистым (никогда не блокировать ответ).
- **R17:** `find_forbidden_cliches` возвращает только коды, не matched-подстроки.

**Логика петли (`verbalize_validated`):**

```
attempt 0: text = await generate_call(base_messages)
           codes = find_forbidden_cliches(text)
           if not codes: return scrubber(text), {attempts:1, retries:0, hits:[]}
for i in 1..max_retries (≤2):
    msgs = base_messages + [retry_message(CLICHE_RETRY_SYSTEM_PROMPT)]
    text = await generate_call(msgs)          # тот же Вербализатор, полная перегенерация
    codes = find_forbidden_cliches(text)
    if not codes: return scrubber(text), {attempts:i+1, retries:i, hits:[]}
# исчерпано:
best = попытка с наименьшим числом кодов (тай-брейк — самая ранняя)
return best_scrubbed, {attempts, retries:max_retries, hits:codes, fallback:True}
```

- **Ретраи строго bounded:** ≤2 → суммарно ≤3 вызова Stage-2. Зацикливание невозможно.
- **Сообщение ретрая** — канон-константа `CLICHE_RETRY_SYSTEM_PROMPT` (F6, миграция):
  «Ты нарушил Negative Constraints и использовал запрещенное клише. Перепиши ответ полностью,
  сделав его естественным.» (**без** цитирования самих клише — grep-тест).
- **Деградация при исчерпании:** F3 → fallback одиночный путь 10.21; F4/F5 → вернуть `best_scrubbed`
  (пользователь всегда получает ответ). Scrubber тегов применяется на **всех** путях (последняя сеть).
- **Ошибка generate при ретрае** → вернуть последний успешный текст (`retry_error` в stats).

### 2.4. Порядок и режимы

- Порядок: `strip_reasoning_tags` → `ID-strip` → (validator-loop живёт в Stage-2, ДО egress).
- `parse_mode=None` (дефолт) — guard работает так же; `parse_mode=HTML` — guard снимает
  reasoning-теги (иначе Telegram вернёт ошибку entities). Markdown/HTML guard не трогает.

### 2.5. Расширение negative constraints (канон)

В `services/prompt_style_blocks.py`:
- Дополнить `ANTI_BOT_BLOCK` запретом шаблонных финалов-обобщений/канцелярских вводных
  («подводя итог», «в заключение», «классика жанра», «как ИИ», «надеюсь, помог», зеркальные
  «нет, ты»), **не цитируя их дословно** (иначе grep-тест отсутствия тропов поймает сам запрет).
- Добавить `CLICHE_RETRY_SYSTEM_PROMPT` (текст ретрая, §2.3).
- Сохранить `ASYMMETRY_BLOCK` (рубленый/непредсказуемый текст).

## 3. Контракты

- Любой **модель-сгенерированный** текст перед `send/edit` проходит `sanitize_outgoing`.
- Тест покрытия: нет прямых `bot.send_message(...)` с переменным текстом вне обёрток
  (allowlist для статичных/UX-строк — только с обоснованием).
- Тесты ложных срабатываний scrubber: `вот факт: это текст` (без цифр) — не режется; `fact:123` —
  режется; `msg:42` — режется; URL/обычные двоеточия — не режутся.
- Тесты детектора: каждый код ловится; легитимные фразы («как интересно») — не ловятся;
  `bullet_list` включается только по флагу.
- **Контракт интеграции (для F3/F4/F5):** Stage-2 вызывается через `verbalize_validated(...)`;
  stats — только коды/числа (R17).

## 4. Feature Flags / Progressive Delivery

- `TELEGRAM_SEND_GUARD_ENABLED` — env-only `ClassVar`, **default ON**, Δ каталога = **0**
  (scrubber тегов в egress).
- `SYSTEM2_VALIDATOR_LOOP_ENABLED` — env-only `ClassVar`, **default ON**, Δ каталога = **0**
  (детектор+петля; OFF → Stage-2 вызывается напрямую, scrubber тегов остаётся).
- Поэтапная раскатка % **не требуется**. OFF-флаг → no-op (совместимость с 10.21).

## 5. Kill-switch / fallback / откат

- Kill-switch: флаги OFF.
- Fallback: scrubber ошибка → не отправлять сырьё (fail-closed); validator — fail-open
  (детектор/ретрай не блокируют ответ; деградация по §2.3).
- Откат: флаги OFF / `git revert` + обратная канон-миграция `prompt_style_blocks.py`.

## 6. Стоимость / латентность

- Scrubber — ноль LLM-вызовов (regex в памяти).
- Validator-loop — **+1…+2 LLM-вызова Stage-2 только при срабатывании** клише (обычно 0).
  Bounded (≤2 ретрая). Логи — counts.

## 7. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | Regex режет легитимный текст | Якоря `\bfact:\d+\b`/`\bmsg:\d+\b` + ложные срабатывания |
| R2 | High | Не все точки отправки охвачены | Реестр `SEND_POINTS` + тест покрытия |
| R3 | Medium | Детектор клише даёт ложные срабатывания → лишние ретраи | Финализированный список + word-boundary + тесты; `bullet_list` только по флагу |
| R4 | Medium | Канон-атомарность (`prompt_style_blocks` читают 8 канонов) | `PREV_*` + один коммит (ADR-1013-3) |
| R5 | Medium | Клише в prompt-константе ловится grep-тестом | Список — в `negative_constraints.py` (код), в промпте — только текст ретрая |
| R6 | Medium | Зацикливание/срыв ретраев | Жёсткий лимит `max_retries=2` + fail-open + деградация |
| R7 | R17/R18 | Секреты/тексты в логах | Только длины/коды/числа |

## 8. Открытые вопросы

- Д-10 **закрыт** UPD3: вето на `string.replace`; scrubber = только теги; клише = validator-loop;
  `GuardedBot`-пояс не требуется. См. `round1022-human-gate-map.md`.

## 9. Задачи

См. `tasks.md` (T-2062…T-2069 + **T-2092** детектор+петля, **T-2093** тесты детектора/петли).



## 10. Реализация (Шаг 4 @Builder, 18.09.2026)

Реализовано: `services/outgoing_guard.py` (`sanitize_outgoing`, `EXTRA_PATTERNS`);
`services/telegram_send.py` (`send_text`/`edit_text_safe`/`send_caption`, реестр
`SEND_POINTS` + `SEND_ALLOWLIST`); `services/negative_constraints.py`
(`FORBIDDEN_CLICHE_PATTERNS`, `find_forbidden_cliches->codes`, `verbalize_validated`).
Канон: `ANTI_BOT_BLOCK` п.7 (без цитат клише), `CLICHE_RETRY_SYSTEM_PROMPT`,
`PREV_ANTI_BOT_BLOCK`/`PREV_STYLE_BLOCKS_SUFFIX`, `PREV_*_R1022`-слепки во всех
8 канонах + `prompt_migrations.py` + `plans/docs/canon/**`. Флаги env-only ON.
Тесты: `test_outgoing_guard_round1022.py`, `test_negative_constraints_round1022.py`.
Клише кодом не вырезаются. Полный pytest 6876/0.
