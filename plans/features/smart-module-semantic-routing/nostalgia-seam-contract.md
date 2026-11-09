# Nostalgia Seam — Frozen Contract
**Feature:** smart-module-semantic-routing / NOST-PROACTIVE  
**Date:** 2026-11-10  **Status:** NOSTALGIA SEAM FROZEN

---

## Decision 1 — Proactive seam interface (NOST-PRO-01..04, 09..11)

**Call site:** `initiative_observer.py::_act_on_opportunity` — существующая ветка,
когда `kind == "memory_recall"` и `horizon == "now"`.

**Вызов:**
```python
candidate = await nostalgia_worker.probe_for_active_context(
    chat_id=chat_id,
    context_messages=window_messages,   # list[dict] — текущее окно Observer'а
    now=int(time.time()),
)
# candidate: dict | None
```

**Контракт `probe_for_active_context`:**
- Входы: `chat_id: int`, `context_messages: list[dict]`, `now: int`
- Находит кандидата через `_pick_candidate_semantic` (см. Decision 3).
- Возвращает `None` — если кандидатов нет ИЛИ семантическая схожесть < порога (`_threshold()`). Silence — валидный исход; лог `[nostalgia] probe: no match | reason=<…>`.
- Возвращает `dict` — структура идентична текущему кандидату `_pick_candidate`, плюс поле `"probe_score": float`.
- **Не отправляет** текст сам — передаёт управление обратно Observer'у через `_delegate_initiative` (существующий путь L647).
- Не изменяет таймер тика NostalgiaWorker (тик — отдельный путь).

**Инициатива:** Observer решает `say/silent`, как для любого другого `memory_recall`. NostalgiaWorker не дублирует transport.

---

## Decision 2 — RandomSource plug-in (NOST-PRO-07, 08, 12, 18 + VMQ-ONTO-01)

**Интерфейс:**
```python
class RandomSource(Protocol):
    def random(self) -> float: ...   # возвращает float в [0, 1)
```

**Точка инжекции:** `NostalgiaWorker.__init__` — параметр `random_source: RandomSource | None = None`.

**Fallback:** `random_source is None` → `import random; random.random`.

**Контракт:** `RandomSource.random()` влияет **только на направление выбора** внутри `_pick_candidate_semantic` (тай-брейкер равновесных весов, Decision 3). Не влияет на истинность/ложность воспоминания, на порог, на решение Observer'а публиковать. Инжекция производится снаружи (тесты, VMQ-адаптер); продакшн-код использует `random.random`.

---

## Decision 3 — Замена `_pick_candidate()` (NOST-PRO-05, 06, 13..17)

**Новый метод:** `_pick_candidate_semantic(chat_id, now, context_messages=None)`.

**Веса:**
```
year_back_lines → base 0.7  ×  (1 + semantic_sim(year_lines, context_messages) × 0.5)
golden fact     → base 0.3 + 0.05×importance  ×  (1 + semantic_sim(fact_text, context_messages) × 0.5)
```
`semantic_sim` — косинусная схожесть эмбеддингов через `self.memory.embed(...)`;
если `context_messages is None` или memory недоступен → `semantic_sim = 0` (деградация к старому поведению).

**Тай-брейкер равных весов (±0.01):** `self._random_source.random()`.

**Silence:** возвращает `None` если `best["weight"] < self._threshold()`.

**GraphRAG/долгосрочная память:** остаётся `fetch_golden_facts` (нет нового пайплайна).

---

## Decision 4 — Тестовые имена (NOST-PRO-19)

| Сценарий | Имя теста |
|---|---|
| Семантически близкое воспоминание → probe возвращает кандидата | `test_probe_returns_candidate_when_context_matches` |
| Нет совпадения → probe возвращает None (silence) | `test_probe_returns_none_when_no_semantic_match` |
| Уже опубликованное воспоминание не повторяется | `test_probe_skips_recently_sent_candidate` |
| Нет memory/year_back → silence с честным логом | `test_probe_silence_when_no_candidates_available` |
| RandomSource тай-брейкер не меняет факт, только выбор | `test_random_source_affects_selection_not_fact` |

---

## Инварианты

- Один transport-путь: только через `handle_initiative` (L10620 `direct_chat_service.py`).
- `probe_for_active_context` не изменяет таймер тика.
- Новые настройки не вводятся; новая функция ON by default (PET_PROJECT).
- Silence логируется, не бросает исключение.
- `RandomSource` не сохраняется в БД, не логируется в payload.

---

## Параллельная безопасность

`probe_for_active_context` — READ_ONLY_PARALLEL (читает память, не пишет).  
`_pick_candidate_semantic` — READ_ONLY_PARALLEL.  
`_delegate_initiative` — SERIALIZE (единственный send-path, без изменений).

---

**NOSTALGIA SEAM FROZEN**

*Architect:* claude-opus-5-5 / ai_server — 2026-11-10  
*Feature owner:* smart-module-semantic-routing / NOST-PROACTIVE
