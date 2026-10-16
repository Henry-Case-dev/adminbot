# SOUL-1 / ARCH-DESIGN — контракт единого Prompt Composer

- **Lane:** ARCH-DESIGN (read-only wrt app code). **Baseline:** master HEAD `a854ad95` + рабочее дерево 2026-10-16.
- **Покрывает:** SOUL-04 §5 (один эффективный Composer), SOUL-03 §4 (иерархия уровней 1–7, SelfModel-совместимость), SOUL-15.5/15.7 (hot apply / no silent degradation), SOUL-04.6 (tool-result, машинные стадии), SOUL-06.6 (0 доп. LLM-вызовов), SOUL-16.4.1/16.4.3 (порядок и единый владелец нормализации — контракт стыка с W3).
- **Вход-зависимости:** `design-source-of-truth.md` (этот же lane), `evidence/direct-runtime-assembly.txt` (реальная сборка), `audit-prompt-matrix.md`.

---

## 1. Что заменяется (одной фразой)

Ни один существующий речевой контур не переписывается. Вводится **один владелец сборки** — `services/prompt_composer.py::compose_prompt(plan) -> PromptManifest` — и **шесть** существующих сборщиков system-сообщения становятся его вызывающими с фиксированным профилем. Композер не пишет в PG, не вызывает LLM, не шлёт ничего; он только читает готовые значения через существующие резолверы и возвращает **immutable** значение (system/user строки + трасса слоёв).

---

## 2. API

```python
# services/prompt_composer.py  (W2, единственный новый владелец сборки)

@dataclasses.dataclass(frozen=True)
class PromptPlan:                       # типизированный вход
    profile: str                        # см. §2.2 (закрытый набор)
    writer: str                         # "l1_planner" | "tool_phase" | "l2_writer" |
                                        # "system2_stage1" | "system2_stage2" |
                                        # "initiative_l1" | "initiative_writer" | "factcheck_*" | …
    chat_id: int
    channel: str = "plain"              # plain | rich
    html_safe: bool = False
    run_id: str | None = None           # корреляция/снапшот хода
    core: PromptPlan.CoreRef | None = None
    identity: IdentityRef | None = None
    response_plan: PlanRef | None = None      # ResponsePlan ИЛИ L1Plan (см. §4)
    expression: ExpressionSettings | None = None
    humor: HumorStrategy | None = None        # comic_strategy=… | None
    lessons: tuple[LessonRef, ...] = ()
    samples: tuple[SampleRef, ...] = ()
    style_policy: StylePolicyRef | None = None
    scoped_requests: tuple[str, ...] = ()
    channel_contract: ChannelContract = ...   # факты/имена/доставка/безопасность (L1-уровень)
    base_prompt: str = ""                     # legacy-база профиля (канал), если профиль её требует

@dataclasses.dataclass(frozen=True)
class PromptManifest:
    system: str
    user_parts: tuple[str, ...]
    layers: tuple[LayerTrace, ...]
    versions: dict[str, str]            # core, style_policy, identity/persona, self_model,
                                        # lessons, samples_library, response_plan, channel
    flags: dict[str, bool]
    conflicts: tuple[ConflictRecord, ...]
    manifest_id: str                    # sha256(system|user|versions)[:16]

@dataclasses.dataclass(frozen=True)
class LayerTrace:
    layer: str          # §3
    block_id: str       # стабильный идентификатор блока
    owner: str          # "core" | "persona" | "self_model" | "l1" | "experience" | "library" |
                        # "style_policy" | "channel" | "legacy_canon"
    source: str         # global | chat | participant | topic | default | code | migrated
    revision: str       # ревизия/хеш источника ("" если не версионируется)
    chars: int
    tokens: int         # тем же оценщиком, что в Experience
    rendered: bool
    skip_reason: str    # "" | core_absent | core_disabled | style_policy_unavailable |
                        # samples_unavailable | lessons_unavailable | persona_disabled |
                        # character_layers_disabled | response_plan_disabled |
                        # verbilizer_modes_disabled | profile:machine_stage | budget_excluded | …
    conflict: str       # "" | conflict_id

def compose_prompt(plan: PromptPlan) -> PromptManifest: ...
def render_effective_layers(manifest: PromptManifest) -> dict: ...   # «покажи effective layers»
def manifest_for_events(manifest: PromptManifest) -> dict: ...        # R17-safe: только трасса/версии
```

Правила API:

1. `compose_prompt` **никогда не бросает**: ошибка любого источника → блок не рендерится + `skip_reason` + notable-событие; сборка продолжается (паритет fail-open существующих слоёв: `mca_style_scope` `resolve_block`, `render_lessons_block`, persona-resolve уже fail-open).
2. Один вызов на LLM-вызов. Никаких «дособрать ещё раз» после генерации — единственное пост-преобразование это нормализация W3 (§6).
3. `render_effective_layers` — публичный API для Prompt Inspector (W6) и для тестов W2/W3: отдаёт порядок слоёв, источник, ревизию, `skip_reason`, `conflict`, токены, Σ токенов и **разницу** с прошлым манифестом по `manifest_id`.
4. `manifest_for_events` не содержит текста промпта (только id/версии/размеры) — сырой текст доступен лишь по RBAC-пути Inspector (SOUL-10.6, SOUL-15.4).

### 2.2 Профили (закрытый набор, «что вообще можно подключить»)

| profile | Кто вызывает | Разрешённые слои | Core |
|---|---|---|---|
| `machine_json` | Direct L1 Planner (`direct_chat_service.py:3640-3642`), Initiative L1 (`:7550-7554`), System2 Stage-1 (`:4095-4097`), factcheck analyst, memory extract/compress, summary L1/L2 | channel_contract + identity-кадр (голова ≤400 симв., `direct_l1.py:555,596-598`) | **нет** (`profile:machine_stage`) |
| `speech_plain` | Direct L2 Writer, System2 Stage-2, Initiative Writer, tool-phase (legacy system), checkup/search/web/youtube verbalizer | все слои, включая Core/Expression/Humor/Samples/Style | да (compact/full по `detail_level`) |
| `speech_rich` | доставка `rich` (deep_research, report) | как `speech_plain` + channel-контракт rich; MODE-конфликты буллитов снимаются существующим `_apply_mode_overrides` (`prompt_style_blocks.py:246-253`) | да |
| `editorial_report` | human-facing Summary/Factcheck публикация | Core **только** если владелец включил редакционную eligibility (owner-decisions d); иначе — channel_contract + style_policy(scope=editorial) без Core | по eligibility |
| `channel_text_only` | plain-текстовые каналы без HTML (summary/factcheck plain) | как `speech_plain`, без HTML-акцентов (`FORMAT_PLAIN_TEXT_BLOCK`, `prompt_style_blocks.py:153-160`) | да |
| `internal_silent` | dreams/lore/nostalgia/dossier/phrases (вне каталога) | channel_contract | по owner-decisions (b) |

Новый профиль = правка закрытого набора в одном месте + тест; произвольная «сборка на месте» запрещена (SOUL-04.1: не набор копий).

---

## 3. Таксономия слоёв и потребители

Порядок рендера = порядок приоритета (раньше = старше). Один блок — один владелец-источник; дублирование текста слоя запрещено (проверяется тестом).

| # | Слой | Содержимое | Источник (существующий) | Кто потребляет |
|---|---|---|---|---|
| 1 | `channel_contract` | техническая база канала/профиля: факты/имена/доставка/безопасность, `FORMAT_*`, ANTI_BOT-техчасть | `base_prompt` профиля (канон канала) + `prompt_style_blocks.format_block` (`:256-265`) | все |
| 2 | `core` | Personality Core (compact/full) + явные owner hard-границы | `character.core` (см. D1 §2.1) | все `speech_*`, `channel_text_only`, `editorial_report` по eligibility |
| 3 | `identity` | имя, биография, устойчивые отношения, owner style (`system_prompt_overrides`), `is_aware_ai`-граница, acquired traits | `bot_persona` (`:241-323`), `mca_self_model.render_frame_block` (`:1763-1812`) | все `speech_*` |
| 4 | `self_model_traits` | проверенные изменяемые черты (rules кадра), позиции(мнения), настроение, factual constraints | `mca_self_model` snapshot/frame (`:1643`, `:1763-1812`) | `speech_*` |
| 5 | `context_lessons` | `<Style_Requests>` (scoped prefs, participant>topic>chat) и `<Verified_Lessons>` (reliability=verified, bounded) | `mca_style_scope.resolve_block` (`:616`), `mca_experience.render_lessons_block` (`:1478-1514`) | `speech_*` |
| 6 | `response_plan` | extent/структура/тон/`delivery_hint`/план ответа + `comic_strategy` | `response_extent.render_extent_block` (`:443`), `direct_l1.build_l2_plan_block` | `speech_*` |
| 7 | `expression` | эмоциональная температура/tone/резкость/неформальность (soft) | новые owner-контролы (`ExpressionSettings`) | `speech_*` |
| 8 | `humor_craft` | приёмы (литерализм/абсурд-эскалация/deadpan/бюрократия/аналогия), не личность; 0 доп. LLM | статический набор W4 (SOUL-06) | `speech_plain/rich` при `comic_strategy != none` |
| 9 | `few_shot` | 1–3 отобранных примера + «почему выбраны» (тестовая подсказка) | Sample Library (W4) | `speech_*` при `flags.humor_library_enabled` |
| 10 | `style_policy_hint` | **короткий** semantic hint активных soft/hard правил (не вся база) | `effective_style_policy` (W3) | `speech_*` |
| 11 | `channel_output` | финальные ограничения вывода конкретного канала (rich/plain, лимит длины, форматы) | `channel_contract` профиля | все |

Не потребители композера: postprocess/валидаторы (факты/имена/форма/safety/утечки/доставка) — они читают результат, а не план; нормализация — единственный пост-проход (§6).

---

## 4. Каноническая точка инъекции Core и сворачивание 6 сборщиков

**Единственный владелец:** `services/prompt_composer.py::compose_prompt` (+ его внутренние рендереры слоёв). Всё, что сегодня собирает system-сообщение, обязано ходить через него при `flags.unified_composer_enabled=true`:

| # | Сегодня | file:line | Становится |
|---|---|---|---|
| 1 | хвост system-промпта tool-loop (база + persona + rules + style + lessons + speech) | `direct_chat_service.py:2344-2394, 2398-2430` | `compose_prompt(PromptPlan(profile="speech_plain", writer="tool_phase", …))` → `payload` (`:2690`) |
| 2 | система вербализатора L2 | `:3942-3953` | `compose_prompt(profile="speech_plain", writer="l2_writer", …)`; при OFF-флаге — текущая ветка байт-паритет |
| 3 | система System2 Stage-2 (тот же композер, что и L2) | `:4115-4131` | `compose_prompt(profile="speech_plain", writer="system2_stage2")`; `modes_on`-ветка OFF сохраняется |
| 4 | система Stage-1 синтезатора (System2) | `:4094-4097` | `compose_prompt(profile="machine_json", writer="system2_stage1")` → только канал-контракт (паритет 1107 симв., dump P5a) |
| 5 | System-сообщения factcheck / search / web / youtube / checkup / summary (пять независимых семейств вне direct-файла) | `factcheck_service.py:181,223,251`; `search_service.py:92`; `web_summarizer_service.py:73`; `youtube_summarizer_service.py:112,147`; `checkup_service.py:47`; `summary_generator.py:987,3765,3805`, `summary_l1_clusterizer.py`, `summary_l2_writer.py` | `compose_prompt(profile=…)`; для human-facing — `speech_*`/`channel_text_only`, для машинных — `machine_json` |

`prompt_style_blocks.compose_verbalizer_system` (`:268-324`) **не удаляется**: он остаётся низкоуровневым рендерером базы/режима/формата и вызывается композером внутри (или как legacy-путь при OFF-флаге). Это сохраняет байт-паритет OFF и не создаёт второго владельца.

**Инъекция Core (единственная точка):** блок `core` вставляется композером ровно один раз, между `channel_contract` (1) и `identity` (3). Для Direct это значит: он попадает и в tool-phase, и в L2 Writer, и в Stage-2 — из **одного** места, поэтому расхождение «в одном вызове есть, в другом нет» физически невозможно.

**Сворачивание дублей:**

- `STYLE_BLOCKS_SUFFIX` (`prompt_style_blocks.py:52`) остаётся ровно одной константой и используется только как часть базовых канонов каналов (данные). **Новых копий не появляется.** Композер трактует уже склеенные каноны как `channel_contract` и не добавляет суффикс повторно (сегодня `compose_verbalizer_system` суффикс не добавляет — он в теле канонов, `chat_prompts.py:248,255,275,280,323`).
- «Токсичные» дубли личностей (≥14 копий) **не переписываются в PG**, а де-приоритизируются: (a) Core рендерится отдельным слоем выше по приоритету, (b) известные слепки канонов получают детерминированную вычистку противоречащих сегментов на сборке — механизм `strip_cap_phrases`/`_CAP_PATTERNS` (`response_extent.py:478-491`) с расширением до реестра `legacy_persona_suppression` (bounded, только для **известных** хешей канонов; кастом никогда), (c) для custom — только витрина конфликта (D1 §4, owner-decisions a).
- Дубль персоны «дважды в одном ходу» (`:2371-2430` и `:3948-3953`) схлопывается по источнику: `identity` собирается **один раз за ход** и передаётся в оба LLM-вызова как один и тот же рендер (`manifest.versions.identity` совпадает в трассах обоих вызовов); повторный рендер `system_prompt_overrides` как «Характер: …» **запрещён**, если тот же текст уже пришёл слоем `core` (`conflict: duplicate_owner_character`, SOUL-03.6).

**Что происходит с 4 «тихими» рубильниками** (аудит §5): они не отменяются, а становятся **явными** состояниями манифеста и событием:

| Рубильник | Сегодня | Становится |
|---|---|---|
| `SMART_VERBALIZER_MODES_ENABLED=OFF` (`:3940,4112`) | молча подставляется `PREV_CHAT_VERBALIZER_R1023` | `base.source=legacy_mode`, `skip_reason=verbilizer_modes_disabled`, notable-событие; Core при этом рендерится (композер ON) — «старый токсичный бот» больше не маскирует новый характер (SOUL-01.5) |
| `flags.persona_enabled=OFF` (`:2357-2359`, `bot_persona.py:259`) | `character_block=''`, сигнала нет | `identity.rendered=false, skip_reason=persona_disabled` + событие; Core остаётся (он не персональное хранилище) |
| `MCA_CHARACTER_LAYERS_ENABLED`/`flags.character_layers_enabled` OFF (`mca_gates.py:1032-1040`) | иной текст персоны (legacy resolve) | `identity.source=legacy_persona`, `skip_reason=character_layers_disabled`, событие |
| `DIRECT_RESPONSE_PLAN_ENABLED=OFF` (`response_extent.py:133-142`) | extent/scrub/max_tokens не применяются | `response_plan.rendered=false, skip_reason=response_plan_disabled`; остальные слои живут |
| (доп.) не гейтованный `scrub_for_plan` на L2 (`:3955-3958` vs гейтованный `:4135`) | L2 чистит legacy-cap даже при выключенных режимах | W2 приводит к единому решению и фиксирует его тестом (это баг-поведение, а не «фича») |

---

## 5. Контракт приоритетов (согласован с существующими)

Уровни SOUL-03 сохраняются как есть; ниже — как они выражаются в композере и что делают существующие контракты.

1. **Технические/функциональные правила, безопасность, подлинность фактов, каналы** — слой `channel_contract`; сюда же `ANTI_BOT`-техчасть, `<Character_Rules>` («мнение vs факт, не выдумывать события», `bot_persona.py:51-57`), anti-leak/egress (`outgoing_guard.py:1-21`), фактчек-верификация (машинные стадии `machine_json`). **Никогда не переопределяется** Core/стилем/планом.
2. **Owner Personality Core + явные owner hard-границы** — слой `core`. Поздние слои не переписывают характер. Legacy `system_prompt_overrides` — **owner-текст уровня 3**, а не второй Core: при конфликте «нет шуток» ↔ Core «характер язвительный» композер выдаёт `conflict` с провенансом, а не вставляет оба указания.
3. **Идентичность/биография/устойчивые отношения/явный owner style** — слой `identity` (существующие `personas.*` + `is_aware_ai`-блок; при активном кадре — `SELF_MODEL_FALSE_BLOCK` **заменяет** `_NO_AI_DISCLOSURE_BLOCK`, `mca_self_model.py:1810-1811`).
4. **Проверенные изменяемые черты SelfModel** — слой `self_model_traits`; сохраняются: precedence (`owner_core→owner_style→scoped_request→derived_traits→state`, `bot_persona.py:45-47`), source ownership (`SOURCE_CHAT/GLOBAL/DEFAULT/ERROR`, `mca_self_model.py:66-69`), guards (`:803-899`), `resolve_is_aware_ai` (`:151`), `select_behavior` (`:1643`). **Core не подменяет черты и наоборот**; черты не переносятся между чатами (сохраняется `_scope_mismatch_reason`, `:1614`).
5. **Scoped per-chat/participant предпочтения + validated Experience** — слои `context_lessons` (`<Style_Requests>`: participant>topic>chat, `mca_style_scope.py:20,295`; `<Verified_Lessons>`: только `reliability=verified`, bounded `ExperiencePolicy`, `mca_experience.py:426-463,1478-1514`); при недоступности Experience — fail-open пусто (SOUL-19: «fail-open при недоступности Experience»).
6. **L1 ResponsePlan** — слой `response_plan`: extent/tone/structure/delivery_hint + **необязательный один** `comic_strategy` (SOUL-05). План **не переписывает** характер; явные пользовательские ограничения формы/длины приоритетнее комической экспансии.
7. **Speech Style Policy** — слой `style_policy_hint` (короткий hint) + исполнение на финальном тексте (W3). Позднее расположение не делает форму старше фактов/безопасности/дословности (SOUL-03). Правила финального чата не применяются к SQL/JSON-планам/поисковым запросам/цитатам/таблицам/машинным стадиям (SOUL-16.4.4) — это обеспечивается профилями: у `machine_json` слой вообще не подключается, у технических сегментов внутри ответа — exempt-логикой W3.

**Исходы конфликта (закрытый набор, попадает в манифест):** `keep_stronger` (слабейшее правило снято), `exempted_protected` (защищённый тип контента), `repaired` (детерминированная локальная правка), `conflict_reported` (требуется решение/видно человеку), `denied` (строгий режим «нигде» честно блокирует несовместимый вывод). Запрещено: молча вставлять два противоречащих указания (SOUL-03.3) и объявлять `styled=true` при провале hard-правила (SOUL-15.7).

---

## 6. Стык с W3: единый пост-проход

Композер владеет **сборкой**; W3 владеет **нормализацией**. Контракт стыка:

- `effective_style_policy` собирается **после** выбора scope/типа выхода и **до** Writer: композер запрашивает у W3-аксессора снимок политики и кладёт в план `style_policy: StylePolicyRef`, в манифест — `versions.style_policy` и hint-слой.
- После генерации ровно **один** проход, порядок фиксирован: `content/evidence invariants → extent check (в т.ч. one_word) → style policy validation/targeted repair → Telegram serialization → outbound validation`. Владелец прохода — новый `services/style_policy.py` (W3) для правил формы; существующие `verbalize_validated` (`negative_constraints`) и `sanitize_outgoing` (`telegram_send.py:105-107`) **остаются** своими шагами внутри этого порядка и не дублируются.
- Идемпотентность: повторный вызов прохода на уже нормализованном тексте = no-op (`repaired=0`), кроме случая, когда правило было выключено между проходами.
- Композер гарантирует, что нормализация получает `manifest` (для `exempted/conflict` и провенанса) и **не** трогает защищённые сегменты; факт «доставлено ровно то, что прошло проверку» подтверждается на payload (SOUL-16.3.4) — seam 5.

---

## 7. Несущие факты repo (как дизайн их учитывает)

| Факт | file:line | Как учитываем |
|---|---|---|
| `prompts.direct_chat_system_prompt` **не читается** L1 и Initiative: они берут `prompts.direct_l1_planner_system_prompt` | L1: `direct_chat_service.py:3640-3642`; Initiative L1: `:7550-7554`; Initiative writer: `:7616-7621` (тот же `_l2_write_answer`) | профиль `machine_json` для обоих L1 (Core нет — машинная стадия); Initiative Writer = `speech_plain` с тем же Core. Ключ `direct_chat_system_prompt` остаётся базой канала tool-phase и не «притворяется» общим ядром |
| Ключ L1-планировщика добавлен в каталог (рабочее дерево) | `param_catalog.py:656` (uncommitted diff) | считаем данностью; W2 не трогает |
| `L1Plan(one_word)` схлопывается в `micro`; `EXTENTS` без `one_word` | `direct_l1.py:146-147`; `response_extent.py:36` | композер принимает `L1Plan` **и** `ResponsePlan` и переносит `extent` как **строку-значение** (`plan.extent_hint`), не через `to_response_plan()`. До фикса W3 значение `one_word` даёт `conflict: one_word_not_supported` в манифесте и рендер текущего micro-текста; после W3 — рендер строгого блока. Никакой alias/legacy-склейки в композере |
| Persisted custom PG перекрывает код-дефолты; миграция дефолтов их не трогает | `prompt_migrations.py:340-343` (custom → skip+WARNING); `chat_params._resolve_from_root:354-377` (override → hot → default) | дизайн **не** зависит от изменения код-дефолтов: Core — отдельный блок; нормализация старых канонов — только известные хеши; custom → витрина и решение владельца |
| 6 независимых сборщиков + ≥14 копий «токсичной» персоны | `prompt_style_blocks.py:268`; `direct_chat_service.py:2344-2430`; `factcheck_service.py:181,223,251`; `summary_generator.py:987,3765,3805`; `search/web/youtube/checkup` (см. D1 §1.2) | все шесть → профили композера (§4); копии не переписываются, а де-приоритизируются |
| Модель/личность рендерится в двух LLM-вызовах одного хода | `direct_chat_service.py:2371-2430` (tool-phase) и `:3948-3953` (L2) | `identity`/`core` рендерятся один раз за ход, версии совпадают в трассах; дубль в одном сообщении запрещён тестом |

---

## 8. Регрессионные швы (топ-5) и что именно проверять

1. **Версии личности** — `mca_self_model.persona_version_hash` (`mca_self_model.py:378-386`), `style_version_hash` (`:389-394`), сборка снимка (`:534-548`, `_snapshot_version:397-411`), LKG (`:967-1005`). Core-revision и style-policy-revision **обязаны** участвовать в версии (иначе hot apply не отражается в snapshot/provenance, а кэш/трасса показывают старую личность). Проверка: правка Core → изменились `persona_version`/`style_version`/`snapshot.version`; при этом смена модели/провайдера версию **не** меняет (инвариант I-2, `:12-14`).
2. **Byte-parity OFF** — `prompt_style_blocks.compose_verbalizer_system` (`:268-324`) + хвосты `direct_chat_service.py:2371-2430,2666-2670,3942-3958`; существующие тесты привязаны к суффиксам (`tests/test_direct_chat_prompts.py:233-276`). Проверка: выключенный флаг даёт system/user **байт-в-байт** и совпадение с хешами из `evidence/direct-runtime-assembly.txt` (P1 2088/709, P2 1936/668, P4 2423/685, P3 1289/431, P5a 1107/342).
3. **`one_word`/`micro`** — `direct_l1.py:139-168` (`to_response_plan`), `:171-190` (`plan_response_mode`), `response_extent.py:36,443-498`. Проверка: композер не теряет `one_word` (манифест + `conflict` до W3), а W3 доводит до payload; `micro` остаётся 2–8 слов.
4. **Kill-switch OFF-ветки** — `direct_chat_service.py:3940-3945` (`modes_on=false`), `:4110-4118`, не гейтованный scrub `:3955-3958`; `mca_gates.py:1032-1077,1410-1421`; `response_extent.py:133-142`. Проверка: каждая OFF-комбинация = документированный паритет + видимая причина в манифесте/событии; ни одна не «тихая».
5. **Доставка/egress** — `direct_chat_service.py:4220-4279` (`_send_direct_answer`, rich/HTML-ветки), `services/telegram_send.py:105-107`, `services/outgoing_guard.py:1-21`, реестр `SEND_POINTS`/`SEND_ALLOWLIST` (`telegram_send.py:40-90`). Проверка: нормализация происходит до финальной сериализации; проверяется фактический payload (после `escape_lore_html`/`strip_lore_html`/`parse_mode`), `message_id`/ссылки/выделения/структура не меняются; новых send-путей нет.

Дополнительные швы, которые нельзя «забыть» в W2 (не топ-5 по риску, но по coupling): `chat_params` резолвер (`chat_params.py:344-377`) и optimistic 409 (`:46,407+`, `routes.py:609-725`); persona API/RBAC (`routes.py:2451-2620`); `mca_experience` лимиты блока (`mca_experience.py:426-463`).

---

## 9. Минимальный набор тестов W2

| Тест | Доказывает |
|---|---|
| `tests/test_soul1_composer_layers.py` | порядок слоёв и принадлежность владельцу; `render_effective_layers` показывает источник+ревизию+`skip_reason`; Core ровно один раз; нет дубля owner-характера (SOUL-04.1/04.2, SOUL-03.6) |
| `tests/test_soul1_composer_parity_off.py` | `flags.unified_composer_enabled=false` → байт-в-байт против текущей сборки и хешей дампа (шов 2) |
| `tests/test_soul1_core_version_propagation.py` | правка Core → `persona_version`/`style_version`/snapshot.version изменились; два чата изолированы; in-flight запрос держит старый снапшот (SOUL-15.5, шов 1) |
| `tests/test_soul1_legacy_custom_preserved.py` | custom `prompts.*` не перезаписан, помечен `custom_legacy`, эффект сохранён, повторный прогон миграции = no-op (SOUL-04.4, SOUL-15.3) |
| `tests/test_soul1_flags_composition.py` | таблица истинности новых × существующих флагов; каждая OFF-ветка = паритет + причина; `humor_feedback=false` не ломает речь (SOUL-15.6/15.7) |
| `tests/test_soul1_machine_profile_no_core.py` | L1/Initiative-L1/Stage-1/factcheck-extract не получают Core/юмор; `machine_json` = только канал-контракт (SOUL-04.6, SOUL-BOUND.4) |
| Негативные (в тех же файлах) | нет второго LLM-вызова (счётчик обращений), нет секретов/PII в манифесте-событиях, ошибка источника → `skip_reason`, не молчание |
