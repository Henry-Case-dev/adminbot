# ASAP2-PROBE — протокол семантической пробы Direct Chat (§6)

**Лейн:** ASAP2-PROBE. **Дата прогонов:** 23.10.2026, 03:52–04:05 (+12:00).
**Кандидат:** HEAD `f7156fee`; проверяемый код — `5ad73933` (fix(asap2) Direct Chat
clarification corrective). Дерево `services/` на `f7156fee` байт-в-байт равно
`5ad73933`: `git diff --stat 5ad73933 HEAD -- services/` → пусто. Код в лейне
**не менялся**.

## 1. Изоляция

- Ни одного соединения с прод-БД/PG, Telegram, SSH. `config.settings` только
  читался (`.env` — read-only); писались только файлы этого каталога.
- Промпты — кодовые каноны `services/chat_prompts.py`, то есть те же байты,
  которые миграция устанавливает в active PG (эффективный PG-payload —
  отдельная зона DevOps/REV-ASAP2-STRUCT, здесь не читался).
- Контекст L1 собирался **боевой функцией** `direct_l1.build_l1_context`
  (секции СООБЩЕНИЕ/ПОСЛЕДНИЕ СООБЩЕНИЯ/УЧАСТНИКИ/ДОСТУПНЫЕ ВОЗМОЖНОСТИ/
  УСЛОВИЯ/ОТВЕТЫ БОТА, кап 1600 токенов), `<Current_Question>` — с тем же
  срезом обращения «Бот,»/`escape_xml_text`, что в `_render_current_question`.
- Речевой сигнал — боевой `claim_envelope.build_speech_understanding` через
  тот же рендер, что `_l1_speech_hints` (без `clarify=ask`, assume сохранён).
- L2 — боевой `compose_verbalizer_system` (канон + mode/extent-блок) и боевой
  `direct_l1.build_l2_plan_block`; user-часть = plan-блок + окно диалога +
  `<Current_Question>`.
- Транспорт: **ровно один POST** на вызов, без скрытого retry-каскада и без
  fallback-модели — чтобы ledger платных вызовов был точным. Три обрыва на
  `getaddrinfo` до отправки запроса (T04) провайдером не оплачены и в ledger не
  попали; повтор после восстановления DNS.

## 2. Модель и sampling

| Параметр | L1 planner | L2 writer |
|---|---|---|
| модель (запрошена/ответила) | `deepseek-v4-flash` (apinet.cloud) | `deepseek-v4-flash` |
| temperature | не передаётся (`l1_temperature(None)` → None) | `0.7` (`settings.tone_temperature(None)`, пресет balanced) |
| max_tokens | `512` (`l1_max_output_tokens()`) | не передаётся (как в Direct не-longform) |
| system (sha256[:12], длина) | `c987c03e3ee0`, 6542 симв. | `d1b210c156c8`, 2827 симв. (+ mode/extent-блок) |

`system_sha12`, `user_sha12`, `messages_sha12`, `finish_reason`, `usage`,
`latency_s` записаны для каждого вызова в `raw/raw-*.json`. Фактическая
serving-модель в ответах провайдера — `deepseek-v4-flash` во всех 37 вызовах.

## 3. Бюджет: 38 из 45 платных вызовов

| Группа | Вызовы | Что не сделано |
|---|---|---|
| preflight связи (1 слово) | 1 | — |
| L1 одиночных сценариев (T01–T09, T12, T13, T15, T16, T25) | 14 | — |
| L1 bounded repair (T04: `finish_reason=length`, пустой content) | 1 | — |
| L1 попытки построить «период»-цепочку (T20-IN, T20-STAT, T20-STAT2, T20-STAT3) + T23-IN | 5 | цепочка T20 не воспроизведена (см. results §5) |
| L2 текстов (T01–T09, T12, T13, T15, T16, T25) | 14 | L2 для tool-маршрутов намеренно не запускался |
| L1 turn2 реальных цепочек (T19, T21, T23) | 3 | L2 turn2 не нужен: план ушёл в tool-маршрут |
| **Итого** | **38** | 7 вызовов остались неиспользованными |

Ledger построчно: `ledger.jsonl` (label + ts + HTTP status).

## 4. Честные ограничения выборки

1. **Один прогон на формулировку**, без повторов и без перебора температур:
   подтверждается отсутствие систематического ложного уточнения на 15
   L1-планах, но не «100 % семантическая корректность» (§8.8 источника).
2. **L2-часть user-контента упрощена**: план-блок + окно диалога +
   `<Current_Question>`. В проде туда же идут персона/стиль/память/lessons и
   tool-evidence. Слои, которые могли бы *сами* приказывать «уточни»,
   проверены отдельно (Speech: §3.3; канон L2: §4.2) и в пробе участвуют
   ровно боевыми байтами. Различия затрагивают тон/полноту, а не факт
   «ответ vs вопрос» — это подтверждено тем, что все 14 текстов не содержат ни
   одного вопросительного знака, кроме двух уместных уточнений.
3. **Tool-маршруты не исполнялись**: где L1 выбрал capability, L2 не
   запускался (нельзя подсовывать выдуманный tool-evidence). Для таких
   сценариев исход фиксируется на уровне плана (`tool_use`) — это ровно тот
   контракт, который проверяется: «не спрашивает снова, продолжает задачу».
4. `persona_frame` и `memory_hints` пустые; `[УСЛОВИЯ]` всегда `FORCE_LINE`
   («прямое обращение к боту: текстовый ответ обязателен»). Так проба измеряет
   семантику уточнения, а не выбор silent/react.
5. Один чат, один язык (ru), синтетические обезличенные контексты. Прогонов на
   реальной приватной трассировке со скриншота нет → причина конкретного
   исторического turn остаётся `UNCONFIRMED` (§6.5 источника), проверяется
   только действующая модель на эквивалентных сценариях.

## 5. Воспроизведение

```powershell
cd C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\asap2_probe
$env:PYTHONIOENCODING='utf-8'
C:\Code\Python\adminbot\.venv\Scripts\python.exe probe.py structural      # 0 вызовов
C:\Code\Python\adminbot\.venv\Scripts\python.exe probe.py l1 T01,T02
C:\Code\Python\adminbot\.venv\Scripts\python.exe probe.py l2 T01,T02
C:\Code\Python\adminbot\.venv\Scripts\python.exe probe.py chain T21
```

Копия раннера: `probe.py`. Ledger обрывает прогон на 45-м вызове
(`assert n < BUDGET`), поэтому бюджет нельзя превысить незаметно.
