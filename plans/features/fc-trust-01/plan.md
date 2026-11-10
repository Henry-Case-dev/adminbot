# FC-TRUST-01 — план исполнения (PM, 11.11.2026)

Источник: `plans/owner_inputs/2026-11-11-fc-trust-01-current-task-excerpt.md` (дословный снимок
`plans/current_task.md` строки 10750-11042, offset `current_task_line = source_line + 10738`).
Машиночитаемые контракты: `requirements-map.json` (208 строк, 141 обязательная, 132 req_id) и `slice-graph.json`.

## Позиция в очереди (подтверждено, не меняется)

| Задача | Состояние в ledger | Примечание |
|---|---|---|
| `vmq-onto-01` | PENDING, coverage_complete | первый по порядку владельца |
| `self-diag-01` | PENDING | второй по порядку владельца |
| `fc-trust-01` | PENDING, `blocked_by: [vmq-onto-01, self-diag-01]` | этот эпик |
| `pvr-fc-corrective-01` | PENDING, `immediately_after:unified-reply` | позиция не менялась |
| `behavior-gates-simplification-01` | BUILDING, `urgent_tier_after:unified-reply` | позиция не менялась, работа не прерывается |

Новые инициативы между `self-diag-01` и `fc-trust-01` не вклиниваются. Ни одна начатая работа не вытесняется.

## Зависимости, которые эпик действительно предполагает

- `unified-reply:UR-SRC-DATE` (PENDING, кандидат 82d21889 на повторном ревью) — даты веб-источника до evidence-пака.
  `FCT-S3-RETRIEVAL` (`FCT-502`) обязан **переиспользовать** этот контракт; свой второй механизм дат не создаётся.
  Жёстко блокирует только датовую часть S3, не весь эпик.
- `unified-reply:UR-20.4…UR-20.8` (PENDING) — поля инспектора хода. `FCT-S6-OBSERVABILITY` показывает фактчек
  в существующих панелях (FCT-901/902), а не строит новый раздел.
- `pvr-fc-corrective-01:FC-BACKEND` — кандидат `a9e91310` уже входит в 2.58.180 (`721bab10`) и в живой 2.58.181
  (`92070d0e`): подстроки FC-01.1…FC-07.2 закрыты, верхнеуровневые FC-01..FC-07 и C4.x остаются PENDING.
- `pvr-fc-corrective-01:FC-RENDER` и `asap-fc-voice-01:FC-VOICE-CONTRACT/FC-EVIDENCE-DEPTH/FC-RENDERER` — те же файлы
  (`services/factcheck_service.py`, `factcheck_prompts.py`, `factcheck_renderer.py`): требуется сериализация писателей,
  а не параллельные ветки. Это блокировка порядка, а не новая работа.

## Волны

**Волна 0 (после обоих эпиков).** `FCT-S0-CAUSE` — адресная сверка: deployed SHA, effective флаги, промпты,
сверка четырёх карт, один реальный trace инцидента, таблица причины с файлами/строками. Здесь же закрываются
`FCT-131…FCT-137` (сверка с PVR-FC/FCP/ASAP-FC/EVOL) и `FCT-209/211/212/214` (порядок, приоритет, предшествование).

**Волна 1.** `FCT-S1-CONTRACT` (Architect): заморозка ClaimUnit+provenance, трёх уровней Candidate/Evidence/Verdict basis,
разделения coverage и execution_status и — ключевое — способа планирования при существующем порядке вызовов
(`run_retrieval` перед Analyst). Без этого решения S2/S3/S4/S5 не начинаются.

**Волна 2 (две независимые полосы, непересекающиеся файлы).**
`FCT-S2-TARGET` (handlers/factcheck.py, factcheck_context.py, factcheck_suitability.py, factcheck_orchestrator.py)
и `FCT-S3-RETRIEVAL` (factcheck_planner.py, search_aggregator.py, safe_fetch.py, factcheck_attribution.py).
Общая точка сшивки — замороженный контракт из волны 1.

**Волна 3.** `FCT-S4-EVIDENCE-VERDICT` (factcheck_service.py, factcheck_prompts.py, evidence_policy.py, relation_evidence.py).
**Волна 4.** `FCT-S5-RENDER` (factcheck_renderer.py, system2_handoff.py).
**Волна 5.** `FCT-S6-OBSERVABILITY` (usage_events.py, pipeline_analytics.py, param_catalog.py, web/api/routes.py, web/app.js).
**Волна 6.** `FCT-S7-ACCEPT` — 30 сценариев §5 на свежем кандидате, включая мутационную проверку Reviewer'а.
**Волна 7.** `FCT-S8-RELEASE` — merge/review/deploy/health, закрытие старых строк по deployed SHA, отчёт.

Параллельность сознательно ограничена: три писателя одновременно допустимы только как S2 ∥ S3, дальше — сшивка.

## Что переиспользуется, а что действительно ново

Полная таблица (по каждой строке) — в `requirements-map.json`, поле `covered_by` у required-строк и `duplicate_of`
у строк-дублей (25 строк). Кратко:

- **Не создаётся заново**: определения вердиктов (FC-04.2…04.5), согласование validator/parts (FC-04.7, C1.9),
  proof_basis (C1.7), безопасность SafeFetcher/SSRF (FC-07.2), версионная инвалидация кеша (FC-05.3),
  запрет дампа промежуточных данных (FCP-01), сохранение L1→L2→Renderer (FCP-06), медиа-зависимость по Reply/forward
  (RC-MED-RELATION-NOT-PRESENCE), регресс маршрутов (RC-S029), допуск явного фактчека (ASAP-FC-ADMISSION-01, 25 строк VERIFIED).
- **Реально новые дельты (P0)**: сырой `search_text` не получает доказательной власти (`FCT-406`, подтверждено в blob
  `services/factcheck_planner.py:1615`), даты провайдера в фактчеке не теряются (`FCT-502`, `:1077` `published_at=None`),
  технический исход не теряет тип (`FCT-603`, `services/factcheck_service.py:1139`), публичная персона ≠ участник чата
  (`FCT-106`, ядро инцидента), `background_only` и роль перепечатки (`FCT-402`, `FCT-403`), honesty лимитов
  (`FCT-311`, `FCT-312`), отдельный `execution_status` (`FCT-601`), «предложение ≠ принятое изменение» (`FCT-503`),
  RAG чата не источник публичной новости (`FCT-315`), effective значения в админке (`FCT-906`, хот-ключ
  `limits.factcheck_max_queries_total` читается, но не объявлен в `param_catalog`), счётчики и трасса (`FCT-903`, `FCT-902`).
- **Контрольная база §0** (4 ссылки ТАСС/MAIL/M24/GARANT) — `FCT-011`: входная база для сверки смысла, не whitelist
  и не заготовленный ответ. `FCT-010` требует воспроизвести инцидент на реальных входах, `FCT-012` запрещает кодировать
  ожидаемый вывод.

## Запреты владельца (проверяются диффом, не декларацией)

`FCT-213`: второй FactCheck, агент-редактор, параллельный SearchAggregator, новые сабагенты, новый общий LLM-пайплайн,
OpenSpec, GitHub Issues/PR как очередь, перестройка эмбеддингов, массовая чистка памяти/промптов.
Пунктов источника, требующих запрещённой сущности, не обнаружено — конфликтов в карте нет.

## Класс архитектуры

`ARCHITECT_REQUIRED`. Триггер: сквозной контракт доказательности + порядок вызовов (deterministic `run_retrieval`
перед Analyst). PM не замораживает этот контракт сам; S2/S3/S4/S5 ждут решения Architect.

## Открытые пробелы происхождения (для оркестратора)

- `ASAP-FC-EVIDENCE-STYLE-02`: ссылка владельца от 31.10 есть (`plans/owner_inputs/2026-10-31-asap-fc-evidence-style.md`,
  раздел current_task.md 1617-1750), но строк требований в картах нет — id встречается только как упоминание.
  Клаусы (per-claim retrieval, честные статусы, trace) исполняются строками `FCT-021/FCT-301/FCT-603/FCT-902`;
  нужно решение, кто владеет строками в ledger.
- `ASAP-FC-ADMISSION-01`: 25 строк в `plans/features/evol/requirements-map.json`, все VERIFIED — переиспользуется.
- Снимок заявлен как «294 строки до 11043»; фактически раздел — 10750-11042 (293 строки контента, последняя строка
  файла без завершающего перевода). Содержимое снимка побайтово совпадает с `current_task.md` 10750-11042 (проверено).

## Гейт

`python <OPENCODE_CONFIG>/tools/requirements_gate.py check --map plans/features/fc-trust-01/requirements-map.json --stage plan`

```
stage=plan inventory=161 manual=47 scoped=0 errors=0
```
