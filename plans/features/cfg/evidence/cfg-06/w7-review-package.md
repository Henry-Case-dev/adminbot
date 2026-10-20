# CFG-06 — пакет для ревью (волны W0–W7)

Дата: 20.10.2026. База: deployed `29cc49ba` (2.58.98). Коммит НЕ выполнялся —
рабочее дерево = кандидат лейнов W0–W7 одной сессии. Стартовая точка ревью:
`plans/features/cfg/cfg-06-build-plan.md` + карта `requirements-map.json`
(slice CFG-06, 90 строк).

## 1. Что строилось по волнам

| Волна | Содержание | Ключевые файлы | Evidence |
|---|---|---|---|
| W0 | аудит двух маршрутов на deployed-байтах (06A.1–10, 06H.1) + оффлайн-трасса 6 проб | — | w0-audit.md, w0-trace.json |
| W1 | широкий адаптивный контекст 200–500, двухуровневый фид, кеш среза | factcheck_context.py | w1-notes/red-green |
| W2 | suitability gate + ContextualClaimResolution (детерминированные) | factcheck_suitability.py | w2-notes, w2-corpus (40 проб, метрики 1.0/0/0) |
| W3 | единый оркестратор run_factcheck + фриз схем + egress-whitelist | factcheck_orchestrator.py | w3-schemas.md, w3-notes |
| W4 | планировщик: осмысленные запросы (фикс 06A.4) + структурный evidence + SafeFetcher | factcheck_planner.py | w4-notes |
| W5 | renderer Telegram-HTML + entity-safe доставка + срез утечки style_note (06A.5) | factcheck_renderer.py; точечно factcheck_service.py (_temporal_verbalize) | w5-renderer.md (чужая полоса) |
| W6 | интеграция: единый retrieval-контур (поиск ДО вердикта, бюджеты), метрики 06G.7, версионирование кешей, cache-hit через renderer, детерминизм запросов | оркестратор/planner/service (аддитивно) | w6-integration.md |
| W7 | композит CFG-06.B (8 сценариев), спор 260, смоук прода, таблица 06G | tests W7 | w7-acceptance.md/json |

Тесты всего CFG-06: **333+ passed** (полный фокусированный прогон W6/W7),
включая route-coverage 2.58.98 (18 CONTRACT), B07-защиту, settings/smart_cache.

## 2. Архитектура кандидата (v2, за флагом)

```
FactcheckRequest (единый вход, 06H.2)
 → build_envelope (provenance, всегда, 06H.3)
 → ConversationContext (W1: 200–500, двухуровнево) + SuitabilityDecision (W2)
 → gate-маршруты: no_claim → canned; ambiguous → персона-уточнение
   (speech_owner_block последним блоком); иначе ↓
 → FactcheckPlan (маршрут = внутренняя ветка: envelope_temporal | legacy_single)
 → [W6] единый retrieval (≤3 осмысленных запроса, дедлайн, EvidenceMap ev-N)
 → ветка: check_claim_envelope | check_claim(search_results=)
 → CheckedVerdict (internal) → build_presentation (egress-whitelist)
 → render_factcheck (W5, HTML) → deliver_factcheck (entity-safe ≤4096)
```

Прод-путь 2.58.98 не меняется (все рубильники default OFF; route-coverage
зелёный; handler renderer/planner не импортирует).

## 3. Границы решений (важно для ревью)

1. **Envelope-ветка сохраняет собственный `temporal_search`** (каскад дат D8 —
   часть temporal-семантики). Единый retrieval-контур в полном смысле — пока
   только legacy-ветка; направление унификации — пост-W6 (w6-integration §2).
2. **Жанровый контракт `factcheck_prompts.py`** (rich-канал «text-only») не
   тронут: разметку добавляет только renderer; LLM не генерирует HTML
   (w5-renderer §6.3). Правки канонов — отдельная работа (ADR-1013-3).
3. **Локальный tool «кто это сказал»** (06G.3) не реализован — атрибуция
   решается резолюцией контекста (reply/topic/quote) + privacy-фильтр.
4. **Gate/CR/планировщик детерминированы** (без LLM): лексика/структура/стемы.
   Субъективные края (сарказм-без-структуры) сознательно уходят в checkable-
   фолбэк — приоритет 06J.2 (ложный отказ дороже).
5. **Поиск «строго по плану ДО вердикта»** в полном смысле достигается для
   legacy-ветки; для envelope — плановый слой даёт presentation-evidence.

## 4. Риски

| Риск | Митигция/статус |
|---|---|
| Регрессия швов 2.58.98 | route-coverage 18 CONTRACT + byte-parity тесты W1/W2/W3; прод-файлы service правились точечно (W5 style_note — байт-защита) |
| Стоимость v2 (поиск планировщика) | ≤3 запроса + дедлайн 10 с + только scope=web; no_claim/ambiguous — ноль запросов; W6-бюджеты |
| Кеш-коллизии перехода | v2-ключи версионированы (fcv2+fp1; envelope tf1); прод/v2 не пересекаются |
| Ложные отказы | корпус W2: false_refusal=0; асимметрия 06J.2 в коде (no_claim только после контекста; неуверенность → checkable) |
| Недетерминизм запросов | устранён в W6 (finditer-термы), подтверждено двумя процессами |

## 5. OFF-паритет

`FACTCHECK_WIDE_CONTEXT_ENABLED`/`FACTCHECK_SUITABILITY_GATE_ENABLED`/
`FACTCHECK_PIPELINE_V2_ENABLED` — default **OFF**. OFF → handler идёт путём
2.58.98 байт-в-байт (тесты W1/W2/W3 + route-coverage); renderer/planner
handler'ом не импортируются (assert в W6-тестах).

## 6. План включения (после релиза, PET-правило)

1. Релиз кандидата штатным деплоем (флаги OFF → поведение = 2.58.98).
2. Включение `flags.factcheck_pipeline_v2` (hot, без рестарта) — сразу во
   всех подключённых чатах (стоячее согласие владельца).
3. Техсмоук после включения: логи (retrieval digest, gate decisions),
   healthz, ошибки; откат — выключить флаг.
4. Живые проверки (06E.4/06G.8, короткий фактчек) — владельцу, опционально.

## 7. Известные вне диффа (не трогать)

- 2 FAIL `test_outgoing_guard_round1022` (aiogram-дрейф `InputRichMessageMedia`).
- 2 FAIL `test_asap7_direct_settings` (v35).
- Тесты W4–W6 до W7 могли касаться `example.org` через SafeFetcher-дефолт —
  в W7-харнесс SafeFetcher замокан полностью (сеть off); прод-поведение
  не затронуто.

## 8. Индекс evidence

w0-audit.md, w0-trace.json, w1-notes/red-green, w2-notes/corpus/red-green,
w3-schemas/notes/red-green, w4-notes/red-green, w5-renderer.md,
w6-integration/red-green, w7-acceptance.md/json, w7-dispute-metrics.json,
w7-review-package.md (этот файл), w7-manifest-sha256.txt.
