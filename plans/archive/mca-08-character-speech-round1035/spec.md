# MCA-08 `mca-08-character-speech` — spec (design-freeze, Step 2 @Architect, 05.10.2026)

- **Фича:** `mca-08-character-speech` (эпик `memory-context-autonomy`, Wave 2; после mca-03/07/22/06).
- **Статус:** `DESIGN_FROZEN` — T-4892 выполнен; санкции T-4893 выданы (см. §9); Builder T-4894+ разрешён.
- **ADR:** `adr-1028-11-character-speech.md` (D1–D12 + AMEND-регистр; Proposed → Accepted по merge, ожидаемый раздел `plans/ARCHITECTURE.md` §115 — следующий свободный на 05.10.2026).
- **Источник:** `plans/current_task.md:436–462` (§12); приёмки §19 `:874–976` (A07 `:888`, A34 `:915`, A42 `:923`, A58–A63 `:939–944`); границы mca-18 §28 `:1486–1607`; MCA-22 `:15383–15385`; план `mca-round1027-plan.md:99–102, 201, 235, 320`; M-MCA07-2 carry-over `mca-round1027-plan.md:320`.
- **Входные документы:** `requirements-map.md` (R1–R4, CA-08-1…10), `tasks.md` (T-4891…T-4915).
- **Базовая точка:** HEAD `192e229` (docs-archive поверх `c27dac8`; код-база 2.58.54), прод **2.58.54**, SQLite **v25**, каталог **488/427/463/105/103/21** (F8 подтверждается на T-4911/deploy), PG — no-op база.
- **Re-верификация 05.10.2026 (git log по файлам):** `bot_persona.py` — последний runtime-коммит `eb2a232` (round 10.14); `direct_chat_service.py` — `9c78760` (mca-22, 2.58.44); `prompt_style_blocks.py`, `negative_constraints.py`, `claim_envelope.py`, `mca_process_registry.py`, `mca_events.py`, `database.py`, `handlers/direct_chat.py` — не новее `7fc2e39`/mca-06 (2.58.49) и `9c78760`/mca-22 (2.58.44); релизы 2.58.50–2.58.54 (ASAP-4.2/4.4) этих областей не касались. Все file:line-якоря requirements-map актуальны.

---

## 1. Scope и трассировка

| REQ | Суть | §spec | Задачи |
|---|---|---|---|
| **MCA08-R1** | Слои характера на read-пути; личность владельца не подменяется; юмор/мнение допустимы; события/люди — только по материалам | §3, §4 | T-4894…T-4897 |
| **MCA08-R2** | Понимание речи (цитата/сарказм/гипербола/отрицание/короткие reply); неопределённость вместо факта; уточнение только при материальной неоднозначности | §6, §7 | T-4898…T-4902 |
| **MCA08-R3** | Явные просьбы по стилю/темам со scope (участник/чат/тема), explicit-only, приоритет/сброс; без максимизации ответов/конфликтов | §5 | T-4903…T-4906 |
| **MCA08-R4** | Постпроцессор — только форма; техметки/JSON не в Telegram; meaning-change fallback с причиной | §8 | T-4907…T-4909 |
| Наблюдаемость mca-17a | стадии/события/виджет-ID (без UI) | §10 | T-4910 |

**В scope mca-08:** применимая pre-SelfModel часть A58–A63 (слои как read-side-контракт, правила мнение/факт, цитата/шутка в ответном пути, адресаты, уточнения); полное закрытие A58–A63 (SelfModelSnapshot, три тумблера, `TraitObservation→BehaviorRule`, BehaviorFrame, legacy-разбор, paired replay 30×3) — **mca-18**; в evidence mca-08 фиксируется вклад, без заявки полного закрытия.
**Явно вне scope:** SelfModel/BehaviorFrame/компилятор черт/три настройки/paired replay (mca-18); Intent/Decision lifecycle и `defer` (mca-09); статистика (mca-15); рандомизация формы (mca-10b); опыт/lessons (mca-16); UI-рендер и диагностические действия (mca-17c); вторые identity/provenance/retrieval/bundle/постпроцессор/очередь/аналитика; `plans/current_task.md` не изменяется (R17/R18).

## 2. Инварианты (сквозные)

1. **OFF-паритет:** каждый kill-switch (K1–K4, §9) OFF → поведение соответствующей поверхности **байт-в-бит 2.58.54** (промпты, payload, ответы, БД-записи); все четыре OFF одновременно — полный паритет.
2. **Вторых механизмов нет:** не создаются вторые identity/provenance/retrieval/bundle/постпроцессор/словарь reason-кодов/сборщик промпта; scoped-просьбы — одна таблица, один сервис; речевые сигналы — фасад над существующими `classify_speech_act`/quote-контуром mca-22.
3. **M-MCA07-2 не занимается:** поля EvidenceBundle `ambiguities/unknown/contradictions` (mca-09), `persona/interests` (mca-18), `local_context` (mca-05) не наполняются; `CoordinatorDecision`/action-schema (`reply/react/silent/tool`) не меняются (граница mca-09, `:496`).
4. **Граница ядра (mca-06 AM-3):** mca-08 не добавляет write-путей к ядру характера; `services/mca_dream_evidence.py:65–97` (`CHARACTER_CORE_WRITE_API`) не расширяется; запись только в derived-слой.
5. **R17:** в журналы/события/отчёты — только ID/коды/числа/версии; сырой текст сообщений и содержимое просьб не пишутся.
6. **mca-18-совместимость:** сигнатуры `resolve_bot_persona`, `build_persona_prompt_block`, `get_traits(limit, chat_id=None)`, `append_traits`, `save_persona` сохраняются; `is_aware_ai` и пустая персона не перепроектируются (зона mca-18), поведение при них не ухудшается.

---

## 3. D1 — Read-side слои характера и швы под mca-18

**Модель слоёв (read-side, без нового хранилища):** источники — существующие PG `personas` (scope first-class) и `persona_traits`.

| Слой | Источник (existing) | Что видно |
|---|---|---|
| `owner_core` | `personas.name/biography` (chat → global → empty) | ядро владельца |
| `owner_style` | `personas.system_prompt_overrides` | настроенный стиль |
| `derived_traits` | `persona_traits` (`get_traits`) | изменяемые черты (derived-слой) |
| `scoped_request` | `mca_style_requests` (§5) | явные просьбы по стилю/темам |
| `state` | `<mood>` (существующий) | временное состояние |
| `opinions_facts` | контракт правила (§4) | мнение vs факт |

**Порядок разрешения конфликтов (§28.4,** `:1560`**), канон-константа:** `owner_core → owner_style → scoped_request → derived_traits → state`. Ядро владельца выше любой просьбы; просьба выше динамики; состояние — последнее.

**Минимальный AMEND `services/bot_persona.py` (аддитивно, только read-API):**
- `CHARACTER_LAYERS: tuple[str, ...] = ("owner_core", "owner_style", "derived_traits")` — доменные слои персоны;
- `CHARACTER_PRECEDENCE: tuple[str, ...]` — канон порядка (выше);
- `@dataclass(frozen=True) CharacterReadContext { persona: BotPersona; traits: tuple[str, ...]; traits_scope: str = "global" }`;
- `async def resolve_character_context(chat_id) -> CharacterReadContext` — REUSE `resolve_bot_persona` + `get_traits(limit, chat_id=None)` (fail-open: PG down → `BotPersona.empty()`, `traits=()`; WARNING без содержимого);
- `build_persona_prompt_block` **не меняется** (формат `<Persona>`/`_NO_AI_DISCLOSURE_BLOCK`/`if not lines: return ""` остаются как есть — зона mca-18).
- **Шов mca-18:** `traits_scope="global"` фиксирует текущую семантику (общий пул, `get_traits` без chat_id); замена выбора/компиляции черт на `BehaviorFrame` — только mca-18, через этот контекст. `get_traits(chat_id=...)`-возможность сохраняется без изменения вызывающих.
- **A58-совместимость:** пустая персона + `is_aware_ai` True/False — паритет не ухудшается (никаких правок этой ветки; полное закрытие — mca-18).

**OFF (K1):** `resolve_character_context`/константы не используются, direct-путь идёт прежними вызовами — байт-в-бит.

## 4. D2 — Anti-generic, правило «мнение vs факт», одна точка применения

- **Одна точка сборки на путь:** слои применяются в существующих композерах:
  - direct/автономный ответ — хвост системного промпта (существующее место `direct_chat_service.py:1897–1911`; persona-блок уже там);
  - System2/verbalizer — через существующий `compose_verbalizer_system` (`prompt_style_blocks.py:248`) новым **опциональным** параметром `character_block: str = ""` (default "" → байт-паритет всех текущих потребителей; добавляется последним part'ом, строго в рамках существующего канона/оффсетов);
  - новых сборщиков промпта нет; порядок блоков payload direct не меняется (просьбы/правила — хвост системного промпта, не user-блоки).
- **`<Character_Rules>` (канон, рендерится ТОЛЬКО когда рендерится непустой persona-блок):**

  ```
  <Character_Rules>
  Своё мнение — это твоя позиция: помечай его как мнение, а не как факт. Обсуждай события, встречи и действия только по материалам диалога; если материалов нет — честно скажи об этом и ничего не выдумывай.
  </Character_Rules>
  ```

  Пустая персона/пустые traits → блока нет (паритет с 2.58.54; пустая персона — зона mca-18).
- **Anti-generic гарантия:** режимы (`casual/serious/deep_research`) и оффсеты `_DEEP_RESEARCH_OVERRIDES` не срезают persona/character-блоки; тесты фиксируют наличие persona-блока и Character_Rules в финальном system/payload для direct и System2-путей при непустой персоне.
- **Мнение vs факт:** поведенческий guard — правило выше + существующие mca-22 write-gates (`claim_envelope.gate_personal_text_write`/`validate_personal_write`); второй provenance/факт-контур не создаётся. Выдуманные события/встречи/действия — запрещены текстом правила; проверка — fixture-байтами и live-приёмкой (§11).
- **Бюджет:** `_estimate_external_payload_tokens` (`:2697–2759`) дополняется учётом Character_Rules/Speech/Style-блоков (числения те же, метод тот же; OFF → прежние числа).
- **OFF (K1):** правила/`character_block` не строятся и не передаются; verbalizer-вызовы без нового параметра — байт-в-бит.

## 5. D3–D5 — Scoped-просьбы по стилю/темам (участник/чат/тема)

### 5.1. Хранилище (D3): одна аддитивная таблица v26

**Решение: аддитивная SQLite-таблица `mca_style_requests` (v26) через реестр mca-14.** Не reuse `user_prefs`/`chat_params`, потому что: `user_prefs.tone_preset` — только temperature-пресет (нет facet/текста/срока/отзыва/темы), расширение её колонками раздваивает модель просьб по двум хранилищам; `chat_params.overrides` — каст строго по каталогу (`get_by_pg_key`) → потребовал бы Δ каталога и не имеет семантики срока/supersede/просьбы-строки; `chat_params.meta` — невалидированный side-channel. `user_prefs.tone_preset` и `/tone` **не дублируются и не мигрируются** (temperature и form-просьбы ортогональны).

DDL v26 (шаг `style_requests`, `_migrate_style_requests_v26`; аддитивно/идемпотентно `CREATE … IF NOT EXISTS`, повтор — no-op, PG — no-op):

```sql
CREATE TABLE IF NOT EXISTS mca_style_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL,
  scope TEXT NOT NULL CHECK (scope IN ('participant','chat','topic')),
  participant_id INTEGER,        -- scope=participant (Telegram user id)
  topic_key TEXT,                -- scope=topic: нормализованная метка
  facet TEXT NOT NULL,           -- закрытый набор §5.3
  directive TEXT NOT NULL,       -- канонический ключ §5.3 (текст серверный)
  set_by INTEGER NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('command','message')),
  source_message_id INTEGER,
  created_at REAL NOT NULL,
  expires_at REAL,               -- NULL = без срока
  revoked_at REAL,
  superseded_by INTEGER,
  CHECK ((scope='participant' AND participant_id IS NOT NULL AND topic_key IS NULL)
      OR (scope='chat'        AND participant_id IS NULL     AND topic_key IS NULL)
      OR (scope='topic'       AND participant_id IS NULL     AND topic_key IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_mca_style_requests_active
  ON mca_style_requests(chat_id, scope, revoked_at, expires_at);
CREATE INDEX IF NOT EXISTS idx_mca_style_requests_participant
  ON mca_style_requests(chat_id, participant_id, revoked_at);
```

Backfill не требуется; старый код таблицу не читает (rollback-safe). `PRAGMA user_version = 26`; backup pre-DDL — существующий fail-closed backup-guard mca-14 (срабатывает автоматически на любой новый шаг; T-4913 проверяет read-back).

### 5.2. Ingestion (D4): explicit-only, две двери — один writer

Один сервис `services/mca_style_scope.py` (единственный механизм; без второго словаря/контура):

1. **Команда `/style` (скрытая, как `/tone`; в `bot_commands.py` НЕ добавляется — меню не меняется):** `/style`/`/style список` — показать активные (bounded ≤10 строк); `/style <фраза>` — participant (self); `/style со мной <фраза>` — participant; `/style чат <фраза>` — chat; `/style тема <label> <фраза>` — topic; `/style off` — сброс своих participant; `/style чат off`, `/style тема <label> off`, `/style всё off` — admin. Ответы — канон-фразы в `services/smartmodule_phrases.py` (новые `CHAT_STYLE_*`); отдельного подтверждающего сообщения нет (нет второго send-path): просьба применяется к текущему ответу (ingestion до сборки контекста).
2. **Детерминированный детектор явных просьб в сообщении:** рассматриваются только сообщения, адресованные боту (force_direct / reply боту / ЛС); закрытая грамматика «фраза-директива + scope-маркер», ingestion выполняется **до сборки контекста**, поэтому принятая просьба применяется уже к текущему ответу. Совпало однозначно → запись; фраза похожа на директиву, но scope/вид неоднозначны → **не пишем** (+`style_request_ambiguous_skipped`); всё прочее — обычное сообщение (без событий).
   - Scope-маркеры: нет маркера → **participant** (минимальный blast-radius по умолчанию); «со мной/мне» → participant; «в этом чате/для всех/вообще/тут» → chat; «по теме X / когда речь о X / если разговор о X» → topic.
   - **Права (reuse, fail-closed):** participant — сам автор; chat/topic — `services.chat_access.is_admin(set_by)` ИЛИ `chat_lore_store.is_chat_admin(set_by, chat_id)`; ошибка проверки → отказ (`style_request_denied`), запись не создаётся.
   - **Explicit-only инвариант:** молчание, отсутствие реакции, шутка, провокация, число ответов/конфликтов — никогда не создают, не усиливают и не отменяют просьбу (нет кода, реагирующего на эти сигналы). Тест-инвариант обязателен.
   - Бюджеты (константы кода, env-override только для TTL): активных строк ≤20/чат, ≤5/участник, принятых записей ≤5/час/чат (при превышении — отказ без события-шума, WARNING), `topic_key` — `[0-9a-zа-яё _-]{2,48}` (casefold, сжатие пробелов; иное → ambiguous_skipped), `source=message` сохраняет `source_message_id`.

### 5.3. Канон-словарь директив (закрытый; серверный текст, пользовательский текст не хранится)

| facet | directive | канон-текст |
|---|---|---|
| verbosity | short | отвечай короче |
| verbosity | long | отвечай подробнее |
| humor | off | без шуток |
| humor | on | можно шутить |
| emoji | off | без смайлов |
| directness | direct | говори прямо, без смягчений |
| directness | soft | формулируй мягче |
| address | ty | обращайся на «ты» |
| address | vy | обращайся на «вы» |

### 5.4. Резолвер, конфликты, срок, сброс (D5)

- **Выбор на ответ (детерминированно, до генерации):** активные = не revoked, не expired, chat_id совпал, participant → `participant_id == адресат`, topic → токены `topic_key` встречаются в текущем сообщении/trigger'е (casefold, границы слов; LLM-классификатора темы нет). Для каждого facet побеждает: **participant > topic > chat**; внутри одного scope/facet — последняя по `created_at,id`. Проигравшие не рендерятся (никакого LLM-слияния). Обоснование порядка: личная явная просьба точнее адресована, тема — контекстнее, чат — общий дефолт; ядро владельца выше всех (§3).
- **Supersede:** запись новой директивы того же (scope, scope-key, facet) ревокает предыдущую (`revoked_at`, `superseded_by`) + `style_request_superseded`. Противоположные просьбы не склеиваются.
- **Срок:** participant — без срока (до сброса/supersede); chat — `MCA_STYLE_SCOPE_CHAT_TTL_DAYS` (env-only, default 7); topic — `MCA_STYLE_SCOPE_TOPIC_TTL_DAYS` (env-only, default 30). Истечение — ленивый фильтр; bounded write-time sweep по чату помечает истёкшие (`style_request_expired`, ≤5 событий за sweep). Фоновых воркеров нет.
- **Сброс:** команды §5.2; сброс admin'ом для chat/topic; participant — сам. Сброс идемпотентен.
- **Рендер (канон; только при непустом результате):**

  ```
  <Style_Requests>
  Просьбы участников (только форма ответа; не меняют факты, смысл, мнение и адресата):
  - [участник] отвечай короче
  - [тема: рыбалка] без шуток
  </Style_Requests>
  ```

  теги scope: `[участник]`, `[чат]`, `[тема: <label>]`; cap 600 символов (лишние строки отбрасываются, добавляется `…`); XML-спецсимволы label экранируются; label не исполняется как инструкция (не является командой/шаблоном, попадает только в строку темы).
- **Точки применения:** хвост системного промпта direct (после Character_Rules) и `compose_verbalizer_system(..., style_directives="")` (новый опциональный параметр рядом с `character_block`; default "" → паритет). Другие потребители композера не меняются.
- **OFF (K3):** команда неактивна, детектор не пишет, резолвер/блок не строятся; таблица не читается/не пишется — байт-в-бит.

## 6. D6 — Речевые сигналы в ответном пути (аддитивно)

- **Фасад** в `services/claim_envelope.py` (дом speech-act-контракта; без нового классификатора): `SpeechUnderstanding` (frozen) + `build_speech_understanding(...) -> SpeechUnderstanding` + `render_speech_block(u) -> str` + `clarify_action(...) -> "none"|"ask"|"assume"`. REUSE: `classify_speech_act` (`:145`), константы `SPEECH_ACT_*`/`GATED_SPEECH_ACTS`, отрицание/шаблоны quote-маркеров; фактические авторы цитат — из существующего mca-22-контура (повторный `quote_resolver`-вызов запрещён).
- **Поля (R17-safe: коды/флаги, без сырого текста):** `speech_act`, `quote`, `quote_attribution ∈ known|unknown`, `reply_parent`, `short_dependency`, `humor_risk`, `negation`, `clarify ∈ none|ask|assume`, `flags: tuple[str,...]`.
- **Носитель:** `<Speech_Understanding>` — хвост системного промпта (после Style_Requests), рендерится только при активном сигнале (`quote|humor_risk|negation|clarify≠none`); канон-ветки: цитата («Цитата принадлежит её автору…»), шутка/сарказм («не превращай в биографический факт»), отрицание («учти отрицание буквально»), clarify (§7). Cap ≤500 символов.
- **EvidenceBundle не трогается:** M-MCA07-2-поля не занимаются; новых полей bundle нет. `CoordinatorDecision`/action-schema не трогаются. Речевой сигнал — только read-side ответа.
- **OFF (K2):** DTO не строится, блок не рендерится, clarify=none — байт-в-бит.

## 7. D7 — Политика уточнения (без правок action-schema mca-09)

- **Материальность (детерминированно):** `ask`, если одновременно: `short_dependency` (сообщение ≤3 слов и из закрытого маркер-набора: «почему/зачем/а как/как так/и что/ну и/что?/он?/она?/это?/правда?/серьёзно?» в любом падеже) **и** нет reply-родителя **и** групповой чат **и** прямой родитель-бот не задавал вопрос (см. anti-loop).
- **Anti-loop (bounded):** если `message.reply_to_message` — от бота и его текст заканчивается на `?`, либо clarify уже выдавался в текущем ответе (он и так выдаётся ≤1 раз), то `assume` вместо `ask`: ответ с явным допущением, без повторного вопроса. Цикл переспрашивания невозможен структурно: ≤1 вопрос на ответ + переспрос-блокировка по родителю.
- **Не-материальное:** ЛС, наличие reply-родителя, команда, содержательный вопрос → `clarify=none`, ответ без оговорок/вопросов.
- Формулировка уточнения — на уровне промпт-инструкции (§6), не шаблон-сообщением; отдельного send-path нет; `silent`/`defer`-семантика не затрагивается (`:494–500`).
- **OFF (K2):** clarify не вычисляется; ответы как в 2.58.54.

## 8. D8 — Постпроцессор «форма только» + meaning-change fallback

- **Один контур:** расширяется существующий `negative_constraints.verbalize_validated` (`:342`) и канон egress `outgoing_guard.sanitize_outgoing`; отдельный paraphrase-модуль запрещён (инвариант `tests/test_mca22_core_round1027.py:810–813`); второй постпроцессор не создаётся.
- **Новые опциональные параметры (default None → байт-паритет):** `form_contract: FormContract | None = None`, `fallback_text: str | None = None`. `FormContract(source_text: str, addressee: str | None = None, roster_names: tuple[str,...] = ())` — строится вызывающим (исходный проверенный черновик: для direct/System2 — финал tool-loop `str(raw)`).
- **Гарды (только при переданном `form_contract` и K4=ON):**
  - **G1 (утечки):** `sanitize_outgoing(candidate) != candidate` (техметки/JSON-маркеры/`<thought>`/target-маркер) → reject `form_guard_leak_blocked`;
  - **G2 (числа/отрицание):** числа нормализуются (пробелы/NBSP/разделители тысяч/десятичная запятая); мультимножество чисел кандидата == исходного; для каждого числа сохранённость «отрицание в окне ±40 символов» (закрытый список «не/ни/никогда/без/нет») — иначе reject `form_guard_rejected`;
  - **G3 (адресаты):** при непустом `roster_names` кандидат не вводит имён ростера, отсутствующих в исходнике (регистронезависимо, границы слов) — иначе reject `form_guard_rejected`. (Сверх этого «позиция/смысл» детерминированно не проверяются — не строим несостоятельный NLP; покрытие — fallback по любому reject + live-приёмка A34.)
- **Fallback:** reject → **≤1** повтор тем же Вербализатором с `FORM_GUARD_RETRY_SYSTEM_PROMPT` (канон: «Перепиши ответ заново, сохранив все числа, отрицания, адресатов и смысл; измени только форму. Не добавляй новых имён и данных.»), повтор тратится внутри существующего bounded-бюджета `verbalize_validated` (≤2 retries всего; бюджет НЕ увеличивается); после reject в повторе или при недоступном бюджете → возврат `fallback_text` (санитизированный), stats `form_fallback=True`; при отсутствии `fallback_text` → лучший вариант + `form_fallback=True` (degraded, честно). Бесконечного редактирования нет.
- **Stats (аддитивные ключи):** `form_guard_rejects` (штук), `form_guard_reason` (код|None), `form_retry` (bool), `form_fallback` (bool); существующие ключи не меняются.
- **Область применения mca-08:** direct + System2 (`_synthesize_direct_answer`); factcheck/summary/прочие потребители композера не меняются (их egress-защита — существующий `sanitize_outgoing` в `telegram_send.py`; второго контракта нет). События: `form_guard_rejected`/`form_guard_leak_blocked` (notable-only).
- **OFF (K4):** новые параметры игнорируются, stats без новых ключей — байт-в-бит.

## 9. Санкции T-4893 (поимённо; Builder не выбирает)

### 9.1. Δ DDL
- **v26**, одна таблица `mca_style_requests` + 2 индекса (§5.1), через реестр mca-14 (`MigrationStep(_SCHEMA_VERSION_STYLE_REQUESTS=26, "style_requests", _migrate_style_requests_v26)`), аддитивно/идемпотентно, PG — no-op, backfill не требуется, `user_version=26`. Backup pre-DDL — существующий fail-closed guard (read-back обязателен в T-4913). Иные таблицы/колонки — **0**.
- `user_prefs`/`chat_params`/`persona_*` схема — **не меняются**.

### 9.2. Δ каталога
- **0.** Новые настройки — env-only `ClassVar` в `config/settings.py`; `param_catalog.py`/TSV вне diff; F8 — **NOT_APPLICABLE** (переиздание не требуется); каталог остаётся 488/427/463/105/103/21. Hidden-команда `/style` в `bot_commands.py` НЕ регистрируется (меню не меняется; прецедент `/tone`/`/persona`).

### 9.3. Kill-switches (env-only, default ON; регистрируются в `mca_gates.KILL_SWITCHES` + `_GATE_RESOLVERS` + Settings `ClassVar`)
| # | Имя | OFF = |
|---|---|---|
| K1 | `MCA_CHARACTER_LAYERS_ENABLED` | нет read-контекста/Character_Rules/`character_block` в verbalizer; ветка persona как 2.58.54 |
| K2 | `MCA_CHARACTER_SPEECH_ENABLED` | нет SpeechUnderstanding/блока/clarify |
| K3 | `MCA_STYLE_SCOPE_ENABLED` | нет ingestion/прав/резолва/блока просьб; `/style` неактивна; таблица не читается/не пишется |
| K4 | `MCA_POSTPROCESS_FORM_GUARD_ENABLED` | `verbalize_validated` как 2.58.54 (клiche-loop+scrubber без form-гардов/fallback) |

Дополнительно env-only (не kill-switch): `MCA_STYLE_SCOPE_CHAT_TTL_DAYS` (7), `MCA_STYLE_SCOPE_TOPIC_TTL_DAYS` (30).

### 9.4. reason_code (единственный словарь `mca_events.REASON_CODES`; второй запрещён; ровно +9)
`style_request_recorded`, `style_request_ambiguous_skipped`, `style_request_denied`, `style_request_superseded`, `style_request_expired`, `clarification_asked`, `clarification_assumption_used`, `form_guard_rejected`, `form_guard_leak_blocked`. Имена событий: `character_layers`, `speech_understanding`, `style_scope`, `postprocess_form` (свободная ось event_name mca-13).

### 9.5. Risk
- **R2** (сознательное решение; PM предварительно оценил R2): новых внешних контрактов/очередей/send-path нет, DDL обратима, ингест закрытой грамматикой с правами; residual-риски и митигации — §12. `threat-failure-analysis.md` **не требуется**. **Эскалация до R3 обязательна** (остановка Builder → @Architect), если всплывёт: (а) хранение/исполнение сырого свободного текста как инструкции; (б) запись chat/topic-scope без admin-проверки; (в) потеря смысла fallback'ом в focused-ревью.

### 9.6. Deploy / rollback / merge
- **Пер-фичевый релиз (CA-11, прецедент mca-06 AM-4):** bump **2.58.54 → 2.58.55**; атомарная пара feat+docs, deploy-doc; миграция v26 идемпотентно при старте + backup-guard; health 200; focused-повтор; `user_version` 26; prod ff без force.
- **Rollback:** soft — K1–K4 `false` + рестарт (OFF=2.58.54); cold — `git revert` фича-коммита (v26 аддитивна, старый код её не читает); restore БД — только аварийный сценарий.
- **Merge:** `plans/ARCHITECTURE.md` **§115** (следующий свободный на 05.10.2026; подтвердить на merge) + ADR-1028-11 → Accepted.
- **Запрещено:** менять `CoordinatorDecision`/action-schema; занимать M-MCA07-2-поля; создавать вторые механизмы из §2.2; реализовывать SelfModel/BehaviorFrame; делать UI-рендер; менять `plans/current_task.md`.

## 10. Наблюдаемость (mca-17a, без шума)

- **Реестр** (`services/mca_process_registry.py`): AMEND `direct.reply` — stages += `character`, `speech`, `form_guard` (+`stages_to_events` на имена выше, `instrumentation`, `event_names`); новый `ProcessDefinition process_id="style.scope"` v1 (stages `ingest/resolve/apply/expire`, `state_source=("mca_style_requests",)`, `enabled_gate="MCA_STYLE_SCOPE_ENABLED"`, widget `"Личность/интересы"`), `_GATE_RESOLVERS` += 4 резолвера.
- **Политика событий (урок M-ASAP31-2):** notable-only — CRUD просьб (recorded/superseded/expired/denied/ambiguous_skipped), clarification_asked/assumption_used, form_guard_rejected/leak_blocked; per-reply событий «успех» для read-side слоёв НЕ создаётся. R17-safe поля (ID/коды/числа). K*-OFF → честный `not_run`/`disabled` в реестре.
- **Виджет-ID для mca-17c (контракт, рендер не делать):** `"Личность/интересы"` (слои/просьбы), `"Ответы (decision/System2)"` (речь/форма).

## 11. Поведенческий план приёмки (без SelfModel)

1. **Focused-контракты (Builder, T-4897/T-4902/T-4906/T-4909):** слои/приоритет/пустые состояния; explicit-only (тишина/шутка/провокация не мутируют state; «просьба другого участника» не влияет глобально); scope/конфликты/supersede/TTL/сброс; права (chat/topic только admin); инвариант «нет пути повышения активности от числа ответов/конфликтов»; речевой фасад (цитата≠утверждение, шутка≠факт, ограничение negative guard), clarify-матрица (ask/assume/none), anti-loop; form-гарды G1/G2/G3 + fallback ≤1 + stats; OFF-паритет каждой K* (байт-сравнение промптов/payload/ответов).
2. **Интеграционные:** direct + System2 с реально включёнными функциями (прецедент `:878`); регресс persona/claim/provenance/quote/verbalizer/bounds-наборов; OFF-матрица ×4.
3. **Микросравнения до/после (offline, без отправки в чат):** 5 детерминированных сценариев (непустая персона; scoped-просьба; цитата; шутка/сарказм; короткое «почему?» под разными родителями) — сравнение собранного system/payload и локального поведенческого среза; без SelfModel и без статистических заявлений.
4. **A63/paired replay 30×3 — только mca-18.** mca-08 evidence фиксирует вклад в A58–A63 и явно пишет, что полное закрытие — mca-18 (no-false-acceptance).
5. **Live (T-4914):** примеры владельца до/после в реальном чате (`:442–444`), адресаты, отсутствие техвставок, живая scoped-просьба, шутка≠биография; недоступное — `PENDING OWNER`, не имитировать (`:15167`).

## 12. Failure-mode register (R2, без threat-файла)

| ID | Риск | Митигация |
|---|---|---|
| FM1 | Инъекция через `topic_key`/промпт-блоки | закрытая грамматика label, cap 48, escape, рендер как условие темы, а не инструкция; правила-канон «форма не меняет факты/адресата»; G1/G2/G3 |
| FM2 | Захват чат-стиля троллем/провокацией | chat/topic — только admin; participant по умолчанию; TTL; rate-cap; сброс; анти-максимизация инвариант |
| FM3 | Ложное срабатывание детектора в обычной фразе | только адресованные боту сообщения; закрытые шаблоны; неоднозначное — не пишем; supersede/сброс |
| FM4 | Постпроцессор теряет смысл (fallback деградирует) | G1–G3 консервативны; ≤1 повтор; fallback = проверенный черновик; stats/события; live A34 |
| FM5 | Промпт-бюджет/конфликты блоков | cap'ы блоков (600/500/–), учёт в `_estimate_external_payload_tokens`, порядок §3, OFF-рубильники |

## 13. Матрица spec → tasks

| Spec § | Задачи |
|---|---|
| §3, §4 (D1/D2) | T-4894, T-4895, T-4896, T-4897 |
| §6, §7 (D6/D7) | T-4898, T-4899, T-4900, T-4901, T-4902 |
| §5 (D3–D5) | T-4903, T-4904, T-4905, T-4906 |
| §8 (D8) | T-4907, T-4908, T-4909 |
| §9.1 (v26), §9.3–9.4, §10 | T-4903 (DDL/ingest), T-4907 (guard), T-4910 (реестр/события) |
| §11 | T-4897, T-4902, T-4906, T-4909, T-4911, T-4912, T-4914 |
| §9.6 | T-4913, T-4915 |

**Статус:** `DESIGN_FROZEN` / `SANCTIONS_ISSUED` — все решения приняты, Builder T-4894+ может стартовать без архитектурных вопросов. Открытых блокеров нет; live-часть — `PENDING OWNER` (T-4914). `plans/current_task.md` не изменялся.
