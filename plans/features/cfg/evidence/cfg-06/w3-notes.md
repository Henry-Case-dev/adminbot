# CFG-06 W3 — единый оркестратор run_factcheck: что сделано

Дата: 20.10.2026. База: deployed `29cc49ba` + незакоммиченные W0–W2 правки лейна.
КОММИТ НЕ СОЗДАВАЛСЯ (коммитит оркестратор). Дельта W3:

| Файл | Тип | Суть |
|---|---|---|
| `services/factcheck_orchestrator.py` | **новый** | единый вход `run_factcheck(FactcheckRequest)` (06H.2), фриз-схемы FactcheckRequest/FactcheckPlan/EvidenceRef/EvidenceMap/CheckedVerdict/FactcheckPresentation, egress-whitelist, persona-реплика, внутренние ветки envelope/legacy |
| `handlers/factcheck.py` | правка | `_pipeline_v2_enabled` + `_factcheck_pipeline_v2` (все входы → один оркестратор за миграционным флагом; OFF → прежняя развилка байт-в-байт) |
| `services/smartmodule_phrases.py` | правка | пул `FACTCHECK_CLARIFY_PHRASES` (уточнение при ambiguous) |
| `config/settings.py` | правка | `FACTCHECK_PIPELINE_V2_ENABLED` (env, default **False**) |
| `tests/test_factcheck_orchestrator_cfg06.py` | **новый** | 16 CONTRACT (TEST-LIFECYCLE: CONTRACT owner=CFG-06): фриз схем ×6 + cross-freeze W1/W2, OFF-паритет, консолидация, маршруты, persona-шов, egress-негативы |

`services/factcheck_service.py` (байт-защищённый legacy-пайплайн), `services/mca_gates.py`, `services/system2_handoff.py`, `services/prompt_style_blocks.py` — НЕ тронуты. Промпт-каноны НЕ тронуты (ADR-1013-3 не требуется — FROZEN-база не менялась; единственный новый текст — inline-инструкция короткой реплики внутри оркестратора, вне канона/реестра). Deviation: унифицированный флаг размещён в оркестраторе, а не в `mca_gates.py` — реестр mca-kill-switch'ей имеет счётные drift-тесты; флаг W3 — feature-local (см. w3-schemas.md §3).

## Один контракт на всех маршрутах (acceptance)

- handler более не выбирает продуктовую ветку при v2: reply/репост/команда/транскрипция → `FactcheckRequest` → `run_factcheck` (06B.1); развилка envelope/legacy — внутренняя ветка плана, K1 остаётся внутренним переключателем ветки.
- Обе ветки зовут сервис теми же аргументами, что прод (тест байт-паритета legacy-ветки: target_text/user_hint/forward_source/chat_id идентичны).
- Кеш: envelope — составной ключ `factcheck_temporal` (as_of внутри payload); legacy — slug `factcheck`, запись после доставки (59.2). Ошибки — те же фразы-семантики (🗿/5.4b/5.5). Пул/кулдаун/typing — как сегодня.
- До EvidenceMap утверждающего вердикта нет (gate-маршруты отвечают до поиска; verdict-стадии без evidence → insufficient — унаследовано от обеих веток). Writer/Renderer-инвариант закреплён Presentation-контрактом (текст после verdict не дополняется фактами; W5 рендерит только links из EvidenceMap).

## Флаги (консолидация)

W1+W2 → один миграционный рубильник `FACTCHECK_PIPELINE_V2_ENABLED` (hot `flags.factcheck_pipeline_v2`, default OFF): внутри v2 широкий контекст и gate подразумеваются независимо от индивидуальных флагов (тест `test_v2_implies_wide_context_and_gate`). Матрица W1×W2×W3 и порядок отката — `w3-schemas.md` §3. OFF-паритет полного прод-пути 2.58.98 доказан (default OFF; тест флага + W1/W2 byte-parity тесты + route-coverage 2.58.98 зелёные).

## Egress-whitelist (acceptance: негативный тест)

Служебные поля живут в CheckedVerdict (internal) и физически отсутствуют в FactcheckPresentation (поля по построению; тесты `test_presentation_fields_frozen_and_service_free`, `test_service_fields_do_not_reach_presentation` — as_of/gate_version/reason_code/enum отсутствуют в asdict); латиница-маркеры служебных полей в тексте срезаются детерминированно (`test_egress_scan_strips_service_markers_from_text`). Ссылки — только EvidenceMap текущего прогона (`test_envelope_branch_cache_and_links`: URL не в plain-тексте до renderer W5).

## Персона-реплики (шов UNIFIED-CORE)

`no_claim_after_context` → canned-пул (по брифу); `ambiguous_needs_clarification` → LLM-уточнение: `_SHORT_REPLY_INSTRUCTION` + `speech_owner_block` ПОСЛЕДНИМ блоком system (тест шва: system ends with persona-block), fallback `FACTCHECK_CLARIFY_PHRASES`; `context_unavailable` → продолжение как сегодня. LLM-вызов — только на gate-маршруте ambiguous (bounded), внутри слота пула.

## Прогон

RED (ImportError без модуля) → GREEN 16/16; полный фокусированный CFG-06 + швы: orchestrator + gate + W1-context + handlers + deep-context + **unified-core route-coverage (18 CONTRACT)** + service + two-call + settings + smart_cache + B07-temporal = **275 passed / 0 failed**. Известные 2 pre-existing v35 фейла asap7_direct_settings — вне диффа, не тронуты.

## Отладочная находка (incidental, pre-existing)

aiogram 3.29.1 `ChatActionSender._worker` вычисляет `self.bot.id` в logger.debug АРГУМЕНТОМ (даже при выключенном debug-логе) — тестовый FakeBot без `.id`/`send_chat_action` приводил к вечному ожиданию `_closed_event`. Фикс в тестовом FakeBot (id + send_chat_action); прод-бот — настоящий aiogram Bot, не затронут. Классификация: unrelated/pre-existing (тест-инфраструктура).

## Готовность к W4∥W5

Схемы заморожены тестами (join-barrier снят): W4 наполняет EvidenceMap/FactcheckPlan (аддитивно), W5 рендерит FactcheckPresentation (parse_mode/links/notice). Контракты — `w3-schemas.md`; точки расширения описаны там же (§6).
