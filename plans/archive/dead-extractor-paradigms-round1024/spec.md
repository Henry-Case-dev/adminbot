# spec.md — F8 `dead-extractor-paradigms-round1024` (живой Сон: paradigms/traits + Empty State)

> Раунд 10.24, Часть 1 (backend-core) · Приоритет **P0** · ADR: **ADR-1024-5** (RE-OPEN 10.18/10.20)
> ТЗ: `plans/current_task.md` UPD2 п.6 (стр. 195–199), UPD3 п.4 (стр. 251–252). Сырые тексты/секреты не цитировать (R17/R18).
> Baseline: HEAD `00eab85`; pytest 7424/0; SQLite v12.

## 1. Цель

Довести данные «Глубокого сна» до генерации и вывода в UI: найти и устранить этап, где тихо падает/скипается экстрактор парадигм и черт личности; развязать traits от paradigms; дать UI явный Empty State с пояснением; обеспечить надёжное извлечение фактов/парадигм о **пользователях**.

## 2. Что уже есть (координаты)

- Оркестратор прогона: `services/dream_worker.py:1479-1641` (`_run_deep_once`); **traits-блок `:1612-1638`, ранние return выше (`:1489/1497/1507/1509/1515/1517/1526/1533/1543/1547/1564/1570/1573`)**.
- Парадигмы: `_write_paradigm` `:1912-1955` (`origin='derived_belief'`, `belief_meta.type='paradigm'`, `weight=0.55`); дедуп `_paradigm_dedup_keys` `:1901-1910`; парсер `services/dream_prompts.py::parse_bridge_answer` (`:237`).
- Traits: `_run_persona_traits_once` `:1793-1899`; источник `get_dream_candidates(..., origins=("bot_self_reply",), since_ts=now-30*86400, limit=50)` `:1811-1814`; без self-фактов → `status='empty'`, `reason=no_self_facts` `:1825-1832`; бюджет `_deep_budget_ok` `:1700`.
- Self-факты создаются: `services/direct_chat_service.py:1427` (+ `summary_memory.py:2330-2367`, `self_reflection.py`).
- Гейты: `memory.dream_enabled` (`:323`), `flags.deep_sleep_enabled` (`:1341/1487`), `flags.persona_enabled` (`:1618-1620`) — defaults `DREAM_ENABLED=False`, `DEEP_SLEEP_ENABLED=False`, `PERSONA_ENABLED=True`.
- Статусы: `persona_state.last_trait_status` (`services/bot_persona.py:82-94,326-354,508`); `bot_persona.record_trait_status`; `_deep_result` `:202-209`.
- API: `web/api/memory_agi.py:455-497` (`/api/memory/deep-sleep`), `web/api/routes.py:1610-1638` (`/api/persona` `dynamic_traits`).
- Лог-хуки: F2 `services/external_log.py` (ADR-1024-1).

## 3. Требуемое поведение

1. **Traits запускаются независимо от исхода paradigm-ветки** — при допустимом прогоне Сна (после `disabled/daily_limit/cooldown` и при `persona_enabled`).
2. Self-факты — приоритетный источник; при отсутствии traits не генерируются, но API отдаёт причину `no_self_facts`.
3. API (аддитивно) отдаёт статус+причину для paradigms и traits; UI может показать Empty State.
4. Причины падения/скипа каждого этапа — в логах (F2), без сырых текстов.
5. Парадигмы о пользователях/факты (graph-extract) извлекаются; повторные прогоны идемпотентны (дедуп по `dedup_key`, cap/FIFO не затирает свежие).
6. `_write_paradigm` и `parse_bridge_answer` не теряют валидные элементы молча.

## 4. Изменения по файлам

| Файл | Изменение |
|---|---|
| `services/dream_worker.py` | Декаплинг traits; явные статусы/причины; `trace_step` на этапах; не терять валидные элементы parse; не глотать ошибки записи (лог с причиной) |
| `services/dream_prompts.py` | `parse_bridge_answer`: сохранять валидные элементы при частичном мусоре (не отбрасывать всю пачку); контракт без изменения канона текста промпта |
| `services/bot_persona.py` | (если нужно) явный reason-статус рядом с `last_trait_status`; без DDL (аддитивно к существующей таблице/полям) |
| `web/api/memory_agi.py` | +`paradigms_status`/`paradigms_reason`/`deep_enabled`/`master_enabled` (аддитивно) |
| `web/api/routes.py` | +`traits_status`/`traits_reason`/`self_facts_count`/`persona_enabled` в persona/cognition payload |
| `config/settings.py` | env-only `DEEP_SLEEP_EXTRACT_FIX_ENABLED` (default ON) |
| `web/index.html` / `web/app.js` | (Часть 2, web-очередь) Empty State `index.html:2509-2537`, `app.js:6274-6315`; адаптер `_traitsAdapter` |

## 5. Контракты

### 5.1. Единый набор причин (строковые коды)

`ok | empty | no_self_facts | persona_disabled | master_off | budget_skip | cooldown | daily_limit | no_anchors | no_context | duplicate | error`

> **UPD (review iter1, F1/F4):** `unchanged` (LLM вернула `{"paradigms":[]}` —
> «связи нет/данных мало») маппится в код **`empty`**, НЕ `duplicate`
> (`duplicate` — только когда все кандидаты уже записаны). Пре-LLM гейты
> `cooldown`/`daily_limit` не пишут `deep_skip` (только `_trace_deep`), поэтому
> в `paradigms_reason` они недостижимы без записи в `memory_dream_log`;
> ограничение намеренное (запись `deep_skip` на каждом блокирующем тике
> сломала бы `last_deep_attempt`/cooldown).

### 5.2. API (аддитивно, R16)

```
GET /api/memory/deep-sleep?chat_id=<id>
  → { enabled, source, paradigms_total, runs_total, last_run_at,
      paradigms[], paradigms_status, paradigms_reason,
      deep_enabled, master_enabled, log[] }

> **UPD (review iter1, F2/F3):** при заданном `chat_id` ВСЕ поля ответа
> (`paradigms[]`, `paradigms_total`, `runs_total`, `last_run_at`, `log[]` и
> причина) скоупятся строго по этому чату — без fallback на глобальные строки
> (`recent_dream_log(..., chat_id=...)`). `chat_id=None` → глобально (как
> раньше). Это устраняет смешение скоупов и чужую причину в Empty State.

GET /api/persona (X-Chat-Id)
  → { ..., persona_enabled, dynamic_traits[],
      traits_status, traits_reason, self_facts_count }
```

- Значения причин — R17-safe (коды, не тексты).
- Fail-open: ошибка БД → нейтральные значения (не 500), причина `error`.

### 5.3. Порядок прогона (псевдо)

```
if not manual and not deep_on:          return disabled
if not manual and limit/cooldown:       return daily_limit/cooldown
traits = await _run_persona_traits_once(...) if persona_enabled else skip(persona_disabled)
paradigms = <ветка якорей/LLM/parse/write; ранние return сохраняются как status>
return _deep_result(status=paradigm_status, paradigms=written, traits=traits)
```
> Точное место вставки traits (до ветки или общий хелпер) — @Builder; инвариант: traits исполняются при допустимом прогоне независимо от `no_anchors/unchanged`.

### 5.4. Идемпотентность

Парадигмы — дедуп `_paradigm_dedup_keys`; traits — `bot_persona.append_traits` (дедуп/cap/FIFO). Повторный прогон не дублирует.

## 6. Тесты

- (a) traits пишутся при наличии self-фактов **даже когда парадигмы пусты** (`no_anchors`/`unchanged`).
- (b) при отсутствии self-фактов — `traits_reason=no_self_facts`, traits не пишутся (без галлюцинаций).
- (c) `persona_disabled`/`master_off` отражаются явно.
- (d) парадигмы пишутся и дедуплицируются; повторный прогон идемпотентен; cap не затирает свежие.
- (e) API отдаёт непустые/статусные ленты и причины.
- (f) `parse_bridge_answer` не теряет валидные элементы при частичном мусоре.
- (g) ошибка записи/LLM видна в логах (трассировка), прогон не падает (fail-open).

## 7. Флаги / Δ

- `DEEP_SLEEP_EXTRACT_FIX_ENABLED` (env-only `ClassVar`, default **ON**) — kill-switch декаплинга; OFF → прежняя последовательность.
- Процедурный kill-switch: `DEEP_SLEEP_ENABLED`/`PERSONA_ENABLED` OFF.
- Δ каталога = 0; Δ DDL = 0 (данные производные, авто-бэкап перед мутациями).

## 8. Риски

- **R1 (High):** traits чаще вызывают LLM → расход фона; ограничен `_deep_budget_ok` + суточный кап.
- **R2 (High):** если мастер-гейты на проде OFF — данных не будет; теперь видно (`master_off`), включение — решение владельца (T-2245).
- **R3 (Medium):** дедуп/cap затрёт историю черт → FIFO-тест.
- **R4 (Medium):** диагностика на проде read-only до бэкапа → сначала бэкап, затем мутации.
- **R5 (R17):** не логировать/цитировать сырые сообщения.

## 9. Критерии приёмки

- В БД появляются парадигмы и черты за актуальное окно (при наличии источников); в UI обе колонки непусты либо показывают явный Empty State с причиной.
- Известны и задокументированы точная причина простоя и условия воспроизведения.
- traits больше не зависят от результата парадигм.
- Повторный прогон идемпотентен; ошибки не глотаются.
- pytest зелёный; регрессов по Dream Sleep/Belief Decay нет.

## 10. Откат

- `DEEP_SLEEP_EXTRACT_FIX_ENABLED=False` / выключение гейтов / `git revert`. Данные производные — авто-бэкап перед прогоном. Δ DDL = 0.

## 11. Артефакты-ссылки

- ADR: `ADR-1024-5.md`; карта: `round1024-architecture.md` §3.4, §5.
