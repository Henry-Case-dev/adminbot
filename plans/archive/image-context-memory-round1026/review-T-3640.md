# A4 `image-context-memory-round1026` — единый Reviewer gate (T-3640)

> **Cycle 2 (T-3640) — текущее решение: `Needs Fixes`.** Заголовочный блок ниже
> сохранён как исторический снимок cycle-1. Актуальные binding-хэши и вердикт —
> в разделе «Cycle 2 (T-3640, повторное ревью)» в конце файла.

- **Feature-ID:** `image-context-memory-round1026` (Эпик 3 «Agentic Intelligence», Wave 4, раунд 10.26)
- **Risk-Level:** **R3** (подтверждён по фактическому diff; понижения до R2 нет — egress приватных данных во внешний генератор и injection-поверхность реальны, см. findings)
- **Status:** **Needs Fixes**
- **Reviewed-Commit:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- **Working-Tree-Hash:** `6a452e93b6f9e03b05d3fd4a46f0c6e4985122f73a7f6585e01ebc48f60b6fbb`
- **Spec-Hash:** `d98aab75d9f08af57d71393cf367f87fb2f7725ed958ee42419c7d52fdc9eb6a`
- **Release policy:** EPIC_ONLY; per-feature deploy/tag/bump запрещены; `APP_VERSION = 2.58.30` (без bump).
- **Gate type:** **feature gate** (не агрегатный эпик-релизный gate).

**Note on hashes.** `Working-Tree-Hash` — SHA-256 детерминированного манифеста:
`REVIEW_MANIFEST_V1` + полный `git diff e8646af` (сырые байты) + `git status --porcelain`
+ для каждого untracked-пути (`git status`) SHA-256 содержимого файлов (рекурсивно для каталогов)
+ `Spec-Hash`. Манифест вычислен на момент ревью; файл `review-T-3640.md` в манифест не входит
(создаётся этим ревью). Любая правка кода/spec/untracked-файлов после этого делает binding устаревшим.

## 1. Git base и инспектированный scope

- База: `e8646af` (`HEAD` == `origin/master`); рабочее дерево несёт незакоммиченный
  epic-release код A2/A3/A5/A6 (≈88 dirty-путей) — ожидаемо.
- A4-sanctioned diff (изменённые tracked): `services/image_generation.py`, `config/settings.py`,
  `services/direct_chat_service.py`, `services/tool_router.py`; новые untracked:
  `services/image_context_memory.py`, `tests/test_image_context_memory_round1026.py`,
  `plans/features/image-context-memory-round1026/{spec.md,adr-1026-19-*.md,tasks.md,evidence.md,threat-failure-analysis.md}`.
- Проверено: `services/tool_schemas.py`, `services/worker_budget.py`, `services/param_catalog.py`,
  `services/tool_loop.py`, `services/summary_memory.py`, `services/pg_db.py`, `web/app.js`, `web/index.html`
  **не содержат A4-маркеров** (`IMAGE_CONTEXT*`/`image_context*`/`memory_context`/`context_required` = 0) —
  scope creep по A4 не обнаружен. Все изменения в этих файлах относятся к A2/A5/A6.

## 2. Checks performed (фактические прогоны ревьюера)

| Проверка | Команда | Результат |
|---|---|---|
| A4 suite | `pytest tests/test_image_context_memory_round1026.py -q` | **34 passed** |
| §104 AST-гейт | `pytest tests/test_unified_image_request_round1026.py::TestBoundsA3 -q` | **7 passed** |
| A2/A3/A5/A6+A4+legacy image | `pytest test_unified_image_request… test_memory_lookup… test_image_daily_limit… test_tool_chains… test_image_context_memory… test_image_generation_round1023 -q` | **219 passed** |
| Полный регресс | `pytest -q` | **9247 passed / 0 failed**, 1 warning (152.98 с) |
| JS | `node tests/js/*.js` | **PASS=47 / FAIL=0** |
| Каталог | param_catalog/Settings | **470 / 427 / 445 / 101 / 99 / 21** (без изменений) |
| Канон | `TOOL_CALLING_TOOLS` | **12**, хвост `get_user_context`; нет `request_reference`/`portrait` |
| Версия | `APP_VERSION` | **2.58.30** |
| Пробелы/CRLF | `git diff --check` | exit **0** |

## 3. Requirement / evidence coverage (Lens 1)

Покрытие REQ-A4-01…17 реализацией и тестами проверено по коду и прогонам:
- §24 разрешение: `_resolve_subject` (alias-матч / first-person), `ambiguous` → 0 чтений досье,
  кандидаты только `user_id`, нейтральный арт + уточнение — тесты `TestNameResolution` (6) зелёные.
- §22/§23 визуальный срез: лексикон + `_PSYCH_DENY` (проверяется первым), `dossier_portrait` — только
  не-визуальный контекст, честный `no_visual_data`, капы ≤8/160, slice ≤3/200, total ≤1200 —
  `TestVisualSlice` (9) зелёные. Сырого досье/чата в промпте нет: в `_build_memory_prompt` попадают
  только классифицированные визуальные факты, bounded slice и ≤160-символьный dossier-контекст.
- §25 5-частная сборка: 5 независимых помеченных блоков + §37 DATA-обёртка, порядок; пример
  «самурай + очки»; байт-паритет `context_required=False` (реальные функции, не mock) — `TestPromptAssembly` (6).
- §37/adversarial: инъекция остаётся в DATA-блоке, нет `system`-разметки, `generator_config`-секреты
  не попадают в промпт, R17-лог без имени/факта/текста/промпта — `TestSection37` (3).
- Интеграция: заглушки заполняются на **обоих** входах (`maybe_handle_keyword`, `_generate_image`),
  маркер `already_handled` исключает двойную генерацию, `context_required` только при субъекте —
  `TestIntegration` (4).
- Kill-switch/границы: A4 OFF → байт-в-байт A3; A3 OFF → legacy, helper не вызывается; канон 12;
  каталог без изменений — `TestKillSwitch` (3) + `TestFlagsAndCanon` (3).
- R3-артефакт `threat-failure-analysis.md`: 12 threat'ов, каждый привязан к существующему named-тесту
  (проверено сопоставлением имён; все тесты присутствуют, включая A3 `TestAlreadyHandled`).

## 4. Focused change audit (Lens 2)

- **§104 AST-гейт** (проверен самостоятельно): `TestBoundsA3::test_104_generator_functions_ast_identical`
  реально делает `git show e8646af:services/image_generation.py` и сравнивает AST
  `generate`/`generate_image`/`generate_image_verbose`/`extract_prompt`/`is_image_keyword`. 7/7 passed.
  `generate_and_send` из set-equal исключён документированно (A5-санкция D2/D7); A4 в него вклада не даёт.
- **direct_chat_service diff** минимален: только проброс `aliases/db/memory` в `maybe_handle_keyword`
  (`:1602-1612`); остальное — A2/A3 (маркер/`resolved_url`). Атрибуты `self.aliases/self.db/self.memory`
  существуют (`:679-682`), в bot.py получают `AliasResolver`/`MemoryManager`/`db` (`bot.py:494-531`).
- **tool_router diff** минимален: `_image_memory_note` (`:317`), блок обогащения в `_generate_image`
  (`:2337-2345`) + `note` (`:2361-2363`). Маркер `already_handled` — до гейта/обогащения. `_memory_lookup_*`
  (A6) не переписан; helper не импортирует `tool_router` (цикл исключён).
- **Data egress:** факты ≤8/≤160 симв., slice ≤3/≤200, total ≤1200 (факты+slice). `context` (dossier,
  ≤160) в total не входит, но ограничен. Пути протекания сырого досье/чата не найдено.
- **R17:** все новые `logger`-вызовы A4 (`image_context_memory.py:151,245,470,521`; `image_generation.py:1399`;
  `tool_router.py:2314,2365`) пишут только id/enum/числа/класс ошибки/латентность — без имён/текста/промпта/ключей.
- **Капы/канон/DDL:** Δ каталога=0, Δ DDL=0 (SQLite v12 покрыт полным прогоном), канон 12.

## 5. Counterexamples checked (не только happy path)

1. **Alias-коллизия с общеупотребительным словом** (см. F1) — воспроизведено.
2. **Точное сходство при неразрешённом субъекте** (см. F2) — воспроизведено.
3. Ambiguous с двумя `Лёха` → 0 чтений досье, кандидаты `[1,2]`, note с уточнением — подтверждено тестом.
4. A4 OFF при полном наборе deps → `context_required=False`, промпт == `extract_prompt` — подтверждено.
5. Инъекция в факт → остаётся внутри DATA-блока, эскалации нет — подтверждено (но только факт-канал, см. N1).
6. `generator_config` с секретом → в промпт не попадает — подтверждено.

## 6. Blocking findings

### F1 — HIGH. Резолв субъекта срабатывает только по совпадению alias-строки; нет защиты от коллизий
→ непреднамеренный egress чужих приватных данных.

- **Location:** `services/image_context_memory.py:167-198` (`_resolve_subject`, alias-матч `:171-184`;
  `_stem`/`_mapping` `:128-142`).
- **Requirement/invariant:** REQ-A4-09 («не определять пользователя исключительно по совпадению
  отображаемого имени»), REQ-A4-02/§22 (только task-relevant; не полное досье), REQ-A4-08/§23
  («не использовать чужие приватные данные без необходимости»), инвариант 2.
- **Evidence (воспроизводимо):** при alias-карте `{"7":"Кот"}` запрос `«Бот, нарисуй кота»` →
  `context_required=True`, `resolved_subjects=[{user_id:7,…}]`, `db.get_user_context_facts` **прочитан**,
  `context_sources=['alias','graph_facts']`. Аналогично `{"7":"Лис"}` + «нарисуй лису», `{"7":"Малыш"}` +
  «нарисуй малыша». Матчинг — по стем-токену (len≥3) без какого-либо иного id-сигнала/корроборации.
- **Impact:** любой участник, чей alias совпал с общеупотребительным словом в generic-запросе другого
  пользователя, «захватывается» как субъект; его приватные факты читаются и встраиваются в промпт
  внешнего генератора без необходимости. Это ровно R3-core риск (T1/T3) и подрывает §24-изоляцию.
  Базовая механика alias-матча задана spec/ADR, но guardrail от коллизий не заложен и не тестируется.
- **Corrective action:** добавить guardrail, не выходя за рамки принятой механики (выбрать минимальный):
  (a) требовать точного совпадения токена с полной нормализованной формой alias (без стем-усечения);
  (b) минимальная длина alias-токена ≥4 и stoplist общеупотребительных слов; (c) при неоднозначности
  «alias-слово vs image-объект» не персонализировать (`none`). Добавить регресс-тест: alias `{"7":"Кот"}`,
  запрос «нарисуй кота» → `context_required is False`, `db.fact_calls == []`.
- **Verification:** новый тест + `pytest tests/test_image_context_memory_round1026.py -q` +
  `TestBoundsA3` (7) зелёные; повторный прогон counterexample’а.

### F2 — MEDIUM (requirement-blocking). Интент «точное сходство» теряется при неразрешённом субъекте
→ нет запроса фото/референса и нет дисклеймера «арт ≠ портрет».

- **Location:** `services/image_generation.py:1402-1409` (`_memory_reply_note`), `services/tool_router.py:317`
  (`_image_memory_note`); источник сигнала — `services/image_context_memory.py:405-408` (`_empty(exact=…)`)
  и `:423-430` (exact вычисляется и для `none`).
- **Requirement:** REQ-A4-08 (§23 «Если пользователь хочет точное сходство, попросить фотографию или
  другой визуальный референс»), REQ-A4-07 (не выдавать арт за достоверный портрет).
- **Evidence:** запрос `«Бот, нарисуй Лёху, нужно точное сходство»` при alias-карте без `Лёха` →
  `context_required=False`, `memory_context.exact_likeness=True`, `empty_reason='unknown_person'`;
  `icm.build_reply_note(mc)` **возвращает** корректный запрос референса, но
  `ig._memory_reply_note(req)` = `''` (гейт по `context_required`), промпт = `'Лёху, нужно точное сходство'`
  без дисклеймера. То есть helper вычисляет флаг, но интеграция его молча отбрасывает.
- **Impact:** пользователь, просящий документальное сходство, получает безусловный арт без честной
  пометки и без запроса референса — прямое нарушение §23/REQ-A4-07/-08 для граничного случая
  «субъект не разрешён».
- **Corrective action:** не терять `exact_likeness` (и `artistic_only` для этого случая): либо выставлять
  `context_required=True` при exact-интенте даже для `none`, либо в `_memory_reply_note`/`_image_memory_note`
  не гейтить по `context_required`, когда `exact_likeness=True`. Добавить тест: `none` + «точное сходство»
  → note содержит запрос фото/референса, промпт не содержит ложного «достоверного портрета».
- **Verification:** новый тест + A4 suite (34→≥35) + `TestBoundsA3` зелёные.

## 7. Non-blocking debt (bounded follow-up)

- **N1 (Low, test strength):** инъекционные ассерты покрывают только факт-канал; нет инъекции через
  `message_slice`/`dossier` (`context`)/`preferences`. Структурно они тоже внутри DATA-блока, но
  регресс-защита неполна. Рекомендуется добавить параметризованный тест по всем каналам.
- **N2 (Low):** `_apply_total_cap` (`image_context_memory.py:340-362`) может превысить бюджет на один
  элемент (первый добавляется безусловно), а `context`-блок не учитывается в total. В текущих
  дефолтах не превышается практически; рекомендуется учесть context в бюджете и задокументировать.
- **N3 (Low, test strength):** `test_a4_off_memory_not_read_byte_parity` проверяет `context_required`/
  пустые заглушки, но не спайит `db.fact_calls`/`memory.calls` — «память не читается» доказано
  косвенно. Рекомендуется явный spy-assert.
- **N4 (Low, maintainability):** helper читает приватные `AliasResolver._aliases` (и `_cache`/`_by_name`
  в fake); связь хрупкая. Рекомендуется публичный аксессор alias-карты.
- **N5 (Low):** `_detect_exact_likeness` — substring-матч по сырому запросу; ложные срабатывания
  возможны («похож как» в ином смысле). Не блокирует; при F2-фиксе учесть.

## 8. Unavailable / external checks

- Живой egress-тест во внешний генератор (реальная сеть/провайдер) не выполнялся — юниты/adversarial
  только; для EPIC_ONLY приемлемо, фактическая доставка 5-частного промпта провайдеру не верифицирована.
- A3 owner-gate `PENDING OWNER VERIFICATION` — внешний, A4 его не закрывает (не блокер данного gate).
- Проверка PG-таблиц резервов (A5) вне scope A4.

## 9. Verdict

**Needs Fixes.** Обе линзы пройдены; критические инварианты §104/канон/каталог/DDL/kill-switch чисты,
R3-артефакт качественный. Однако подтверждены **F1 (High)** — непреднамеренный egress чужих приватных
данных через alias-коллизию, и **F2 (Medium, requirement-blocking)** — потеря exact-likeness/дисклеймера
при неразрешённом субъекте. После исправлений повторить: исходные findings, затронутые REQ-A4-07/-08/-09,
A4 suite (34→≥35), `TestBoundsA3` (7), full pytest (≥9247/0), JS (47), catalog counts, `git diff --check`.

@Orchestrator: это **feature gate** (не агрегатный эпик-релизный gate). Machine checkpoint не трогаю;
коммиты/деплой/DevOps не выполняю.

---

# Cycle 2 (T-3640, повторное ревью после rework Builder)

- **Feature-ID:** `image-context-memory-round1026` (Эпик 3, Wave 4, раунд 10.26)
- **Risk-Level:** **R3** (без изменений; egress приватных данных остаётся реальным, см. F1)
- **Status:** **Needs Fixes**
- **Reviewed-Commit:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- **Working-Tree-Hash (cycle 2):** `85e909e6c0072219d99ee025c779e3ef5cb417a3803c83143bafa9b1f7905a6b`
- **Spec-Hash:** `d98aab75d9f08af57d71393cf367f87fb2f7725ed958ee42419c7d52fdc9eb6a` (не изменён)
- **Gate type:** **feature gate** (не агрегатный эпик-релизный gate).
- **Scope cycle 2:** фокусное повторное ревью F1/F2 и затронутых проверок; история cycle-1 сохранена выше.

**Recipe `Working-Tree-Hash` (cycle 2, воспроизводимо).** SHA-256 от конкатенации, в порядке:
(1) литерал `REVIEW_MANIFEST_V1\n`; (2) сырые байты вывода `git diff e8646af`; (3) сырые байты
`git status --porcelain`; (4) для каждого sorted untracked-пути из `git status` — путь, затем SHA-256
содержимого (для каталогов — рекурсивно, sorted, относительные пути через `/`); (5) `Spec-Hash`.
Путь `plans/features/image-context-memory-round1026/review-T-3640.md` исключён явно (создаётся/ведётся
этим ревью). Хэш отличается от cycle-1, т.к. код rework изменил diff и untracked-содержимое (см. ниже).
Любая правка кода/spec/untracked-файлов после этого делает binding устаревшим.

## C2.1. F1 — verification (закрыт ли egress чужого досье через alias-коллизию?)

Прогнаны заявленные проверки и **независимый counterexample ревьюера** (собственный probe вне репозитория,
реальный `build_image_memory_context`, не mock; alias, дающий один кандидат):

| Случай (alias + запрос) | context_required | субъект | `db.get_user_context_facts` | факт в промпте | Оценка |
|---|---|---|---|---|---|
| `{"7":"Кот"}` + «нарисуй кота» (исходный repro) | False | — | 0 чтений | нет | исправлен |
| `{"7":"Лис"}` + «нарисуй лису» (исходный repro) | False | — | 0 чтений | нет | исправлен |
| `{"7":"Малыш"}` + «нарисуй малыша» (исходный repro) | False | — | 0 чтений | нет | исправлен |
| `{"7":"Тигр"}` + «нарисуй тигра» | **True** | uid=7 resolved | **прочитан** | **«носит очки»** | **LEAK** |
| `{"7":"Ромашка"}` + «нарисуй ромашку» | **True** | uid=7 resolved | **прочитан** | **да** | **LEAK** |
| `{"7":"Зайка"}` + «нарисуй зайку» | **True** | uid=7 resolved | **прочитан** | **да** | **LEAK** |
| `{"7":"Роза"}` + «нарисуй розу» | **True** | uid=7 resolved | **прочитан** | **да** | **LEAK** |
| `{"7":"Панда"}` + «нарисуй панду» | **True** | uid=7 resolved | **прочитан** | **да** | **LEAK** |
| `{"7":"Лисичка"}` + «нарисуй лисичку» | **True** | uid=7 resolved | **прочитан** | **да** | **LEAK** |
| `{"7":"Лёха"}` + «нарисуй Лёху» (positive) | True | uid=7 resolved | прочитан | — | корректно |
| `{"7":"Сергей"}` + «нарисуй Сергея» (positive) | True | uid=7 resolved | прочитан | — | корректно |
| `{"7":"Лёв"}` + «нарисуй Льва» (<4, boundary) | False | — | 0 чтений | нет | over-block (не leak) |

**Вывод:** три исходных repro и короткий токен закрыты, но **класс дефекта сохранился**: любое
4+ символьное общеупотребительное image-слово/никнейм, отсутствующее в `_ALIAS_STOPLIST`, снова
захватывает чужое досье. «Тигр», «Роза», «Панда», «Зайка» — реалистичные никнеймы участников чата;
«нарисуй тигра/розу/панду/зайку» — рядовые image-запросы. Обратите внимание: стоплист содержит
`заяц`/`лиса`, но **не** их производные (`зайка`, `лисичка`), т.е. обход возможен даже в пределах
задуманной лексики. Это тот же egress-вектор, что и в cycle-1 F1 (REQ-A4-09/-02/-08, §24-изоляция),
поэтому F1 **остаётся блокирующим (High)**.

Причина: единственный «image-object-фильтр» в guard'е — это конечный стоплист (`_alias_stems:198-214`
проверяет только `len>=4` и `word in _ALIAS_STOPLIST`). Общего классификатора image-объектов в
`_resolve_subject` нет; формулировка evidence «image-object classification on normalized token»
описывает именно membership-проверку стоплиста, а не классификацию. Конечный список принципиально
неполон, поэтому исправление сдвигает границу, но не закрывает класс.

Заявленные тесты `TestAliasCollisionGuard` (6) + `TestExactLikenessGate` (4) + `TestKillSwitch` (4) +
`TestSection37` (6) — **20 passed**; A4 suite — **48 passed**. Т.е. тесты зелёные, но они не покрывают
нестоплистованные image-слова, и потому не опровергают residual leak.

## C2.2. Adjudication F1(a): guard vs REQ-A4-09 / REQ-A4-08

Решение по вопросу «достаточен ли текущий guard или нужен строгий exact-match / дизайн-рулинг»:

1. **Спецификация vs безопасность.** Spec §3.1 действительно предписывает casefold + один
   консервативный стем (нужен для склонений: «Лёха»↔«Лёху»). Полное удаление стемма − это
   spec-strictness-конфликт, и я **не** требую его «в лоб». Но конструктивное требование F1 из
   cycle-1 (a/b/c) было: строгий exact-token, **либо** min-length+stoplist, **либо** «alias-слово vs
   image-объект → не персонализировать». Builder выбрал только (b) с замкнутым списком.
2. **REQ-A4-09** («не определять исключительно по совпадению отображаемого имени»): текущее решение
   по-прежнему определяет субъекта **исключительно** строковым совпадением стемов отображаемого имени
   — добавочного id/корроборационного сигнала нет. Фильтры (длина/стоплист) лишь сужают множество
   ложных срабатываний и не превращают это в не-«исключительно по имени».
3. **REQ-A4-08** («не использовать чужие приватные данные без необходимости»): для «Тигр/Роза/Панда/
   Зайка/Лисичка» чтение чужого факта и его попадание в промпт внешнего генератора **не необходимо** и
   воспроизводится. Значит REQ-A4-08 не выполняется для этих входов.
4. **Реалистичность.** Предусловие leak'а (в чате есть участник с таким alias) — то же самое, что и у
   исходных Кот/Лис/Малыш; если cycle-1 признал те случаи High-реалистичными, то Тигр/Роза/Панда/
   Зайка/Лисичка — тоже. Это **не** теоретическое расхождение со строгостью spec.
5. **Итог.** Так как воспроизводим реалистичный leak → **Needs Fixes** с конкретными входами (таблица
   C2.1). Замкнутый стоплист не является достаточным закрытием. Durable-направление (не предписываю
   код): соотносить токен-кандидат с существующим image-лексиконом/классификацией (`_VISUAL_LEXICON`/
   `_classify_visual`) или ввести независимый сигнал идентификации, сохранив склонения spec §3.1.
   Если Builder считает, что конечный стоплист — это и есть предел, задуманный spec/ADR, то это
   **design-рулинг Architect** (я его не выношу), т.к. он затрагивает принятую механику §3.1.
6. **Устаревание подхода.** Если cycle 3 просто допишет в стоплист ещё слова, это не будет материальным
   прогрессом: класс останется открытым на любой не перечисленной лексеме. Это — основание для
   Architect root-cause, если закрытие не изменится концептуально.

## C2.3. F2 — verification (закрыт)

Независимый probe ревьюера + `TestExactLikenessGate` (4 passed):

| Вход | context_required | exact_likeness | note (direct/tool) | промпт |
|---|---|---|---|---|
| «нарисуй Лёху, нужно точное сходство» + НЕизвестный «Лёха» | False | True | **запрос фото/референса + «не документальный портрет»** (оба входа) | A3-parity (`extract_prompt`), без фактов |
| то же + разрешённый «Лёха» | True | True | запрос фото/референса присутствует | 5-частный (не parity) |
| «нарисуй Лёху» без exact + НЕизвестный | False | False | пусто (оба входа) | A3-parity |

Гейт `context_required OR exact_likeness` (`image_generation.py:1412`, `tool_router.py:328`) работает;
исходный F2 (потеря intent'а при неразрешённом субъекте) закрыт, регресс байт-паритета сохранён.

## C2.4. N1/N3 — spot-check

- **N1:** `TestSection37::test_injection_slice_stays_data` / `_dossier_` / `_preferences_` действительно
  ассертят структуру промпта: наличие DATA-метки, `prompt.index(injection) > index(label)`, отсутствие
  `system`, `startswith("ЗАПРОС:")`. Каналы slice/dossier/preferences покрыты. ОК.
- **N3:** `TestKillSwitch::test_a4_off_no_memory_reads_at_all` спайит `db.fact_calls == []` **и**
  `mem.calls == []`. Прямой spy-assert присутствует. ОК.

## C2.5. Regression (повторные прогоны ревьюера)

| Проверка | Результат |
|---|---|
| A4 suite `pytest tests/test_image_context_memory_round1026.py -q` | **48 passed** |
| Focused (AliasCollisionGuard+ExactLikenessGate+KillSwitch+Section37) | **20 passed** |
| §104 AST-гейт `tests/test_unified_image_request_round1026.py::TestBoundsA3` | **7 passed** |
| Полный регресс `pytest -q` | **9261 passed / 0 failed**, 1 warning (158.07 с) |
| JS `tests/js/*.js` (каждый файл) | **47 pass / 0 fail** |
| Каталог | **470 / 427 / 445 / 101 / 99 / 21** (445 подтверждён зелёными тестами полного прогона; остальное — прямым probe) |
| Канон | **12**, хвост `get_user_context`, нет `request_reference` |
| `APP_VERSION` | **2.58.30** (без bump) |
| `git diff --check` | exit **0** (только LF→CRLF warning'и) |
| Scope creep | A4-маркеры только в санкционированных файлах (`image_context_memory.py`, `image_generation.py`, `tool_router.py`, `direct_chat_service.py`, `config/settings.py`, новый тест) — новых файлов/маркеров A4 вне scope не найдено |

## C2.6. Binding

- `Reviewed-Commit`: `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- `Working-Tree-Hash`: `85e909e6c0072219d99ee025c779e3ef5cb417a3803c83143bafa9b1f7905a6b` (recipe — см. выше)
- `Spec-Hash`: `d98aab75d9f08af57d71393cf367f87fb2f7725ed958ee42419c7d52fdc9eb6a` (без изменений)

## C2.7. Verdict cycle 2

**Needs Fixes.** F2 закрыт и подтверждён независимо; N1/N3 закрыты; регресс-числа соответствуют
заявленным (9261/0, JS 47, TestBoundsA3 7, каталог без изменений, diff --check 0). Однако **F1 остаётся
блокирующим (High)**: воспроизведён реалистичный egress чужого досье для alias «Тигр/Роза/Панда/Зайка/
Лисичка» + соответствующий image-запрос. Замкнутый стоплист + min-length — недостаточное закрытие
класса; REQ-A4-09/-08 для этих входов не выполняются.

Для cycle 3 повторить: исходные три repro, **добавленные counterexamples C2.1** (pos+neg), F2-набор,
`TestBoundsA3`, полный pytest, JS, каталог, `git diff --check`. Если cycle 3 не изменит подход
концептуально (только дополнение стоплиста) — это отсутствие материального прогресса после двух циклов,
и следующий шаг — **Architect root-cause** по дизайн-напряжению «spec §3.1 стемминг ↔ REQ-A4-09
не-резолв по имени».

@Orchestrator: **feature gate**, решение cycle 2 = **Needs Fixes** (F1). Machine checkpoint не трогаю;
коммиты/деплой/DevOps/Scanner не выполняю.

---

# Cycle 3 (T-3640, повторное ревью после root-cause D13 + build T-3646)

- **Feature-ID:** `image-context-memory-round1026` (Эпик 3, Wave 4, раунд 10.26)
- **Risk-Level:** **R3** (без понижения: egress приватных данных остаётся воспроизводимым, см. C3-H1)
- **Status:** **Needs Fixes**
- **Reviewed-Commit:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- **Working-Tree-Hash (cycle 3):** `3d1d8021f01eaf529d70ac2a85468e958f3e957e99dc5cdbd9fc84e846278f74`
- **Spec-Hash:** `63064ccbd5891bde4082d365e7c52def0e0640529a06f3eaa0fe632e33f840c7`
- **Gate type:** **feature gate** (не агрегатный эпик-релизный gate).
- **Scope cycle 3:** class-closure (D13), все prior repros, positive/ambiguous/G2, F2-adjudication,
  N1/N3/F2-retained, spec-conformance, полный регресс. История cycle-1/2 сохранена выше.

**Recipe `Working-Tree-Hash` (cycle 3, идентична cycle-1/2).** SHA-256 от конкатенации, в порядке:
(1) литерал `REVIEW_MANIFEST_V1\n`; (2) сырые байты `git diff e8646af`; (3) сырые байты
`git status --porcelain`; (4) для каждого sorted untracked-пути из `git status` — относительный
путь (utf-8), затем **сырые байты содержимого** (для каталогов — рекурсивно, `dirs`/`files` sorted,
относительные пути через `/`); (5) `Spec-Hash` (ascii). Путь
`plans/features/image-context-memory-round1026/review-T-3640.md` исключён явно. Хэш отличается от
cycle-1/2 (код/tests/spec изменились). Любая правка кода/spec/untracked-файлов после этого делает
binding устаревшим.

## C3.1. Class closure — независимые probes ревьюера (собственные входы, реальный helper)

Метод: собственные fakes (не repo-фикстуры), реальный
`build_image_memory_context`; alias `{"7": <X>}` + `get_persona_names=[<X>]` (т.е. precondition
leak'а максимально благоприятен) + подтверждённый визуальный факт «<X> носит очки».
Колонка **facts** = число вызовов `db.get_user_context_facts` (0 = утечки нет).

**A. Голый запрос «нарисуй X» (без person-маркера):**

| X (alias) | Запрос | context_required | facts | empty_reason | Оценка |
|---|---|---|---|---|---|
| Акула | «нарисуй акулу» | False | 0 | no_person_intent | ok |
| Феникс | «нарисуй феникса» | False | 0 | no_person_intent | ok |
| Дельфин | «нарисуй дельфина» | False | 0 | no_person_intent | ok |
| Кактус | «сделай картинку кактуса» | False | 0 | no_person_intent | ok |
| Кошечка (deriv кошка) | «нарисуй кошечку» | False | 0 | no_person_intent | ok |
| Собачонка (deriv собака) | «нарисуй собачонку» | False | 0 | no_person_intent | ok |
| Медвежонок (deriv медведь) | «нарисуй медвежонка» | False | 0 | unknown_person | ok |
| Рыбка (deriv рыба) | «нарисуй рыбку» | False | 0 | no_person_intent | ok |
| Солнышко (deriv солнце) | «нарисуй солнышко» | False | 0 | no_person_intent | ok |
| Звёздочка (deriv звезда) | «нарисуй звёздочку» | False | 0 | no_person_intent | ok |
| Кварк (вне лексиконов) | «нарисуй кварк» | False | 0 | no_person_intent | ok |
| Телескоп (вне лексиконов) | «нарисуй телескоп» | False | 0 | no_person_intent | ok |
| Клавесин (вне лексиконов) | «нарисуй клавесин» | False | 0 | no_person_intent | ok |
| Барокамера (вне лексиконов) | «нарисуй барокамеру» | False | 0 | no_person_intent | ok |
| **Фотон** | «нарисуй фотон» | **True** | **1** | — | **LEAK** |
| **Фото** | «нарисуй фото» | **True** | **1** | — | **LEAK** |
| **Фотоаппарат** | «нарисуй фотоаппарат» | **True** | **1** | — | **LEAK** |
| **Фотография** | «нарисуй фотографию» | **True** | **1** | — | **LEAK** |
| **Фотомодель** | «нарисуй фотомодель» | **True** | **1** | — | **LEAK** |
| **Снимок** | «нарисуй снимок» | **True** | **1** | — | **LEAK** |
| **Портретист** | «нарисуй портретиста» | **True** | **1** | — | **LEAK** |
| **Досье** | «нарисуй досье» | **True** | **1** | — | **LEAK** |
| Выглядит (глагол) | «нарисуй выглядит» | False | 0 | no_person_intent | ok |
| Внешность | «нарисуй внешность» | False | 0 | no_person_intent | ok |

**B. Spurious G1 через предлог (тоже голые/полуголые generic-запросы):**

| X (alias) | Запрос | facts | Оценка |
|---|---|---|---|
| Кварк | «нарисуй кварка **про** космос» | 1 | **LEAK** |
| Закат | «нарисуй закат **про** море» | 1 | **LEAK** |
| Город | «нарисуй город **об** огнях» | 1 | **LEAK** |

Egress подтверждён end-to-end для «Фотон»/«нарисуй фотон» (alias `{"7":"Фотон"}`,
roster `["Фотон"]`): `context_required=True`, `resolved_subjects=[{user_id:7, name:"Фотон",
resolution:"resolved"}]`, `db.get_user_context_facts` вызван, и **факт «носит очки и бороду»
присутствует в `build_final_prompt`** (часть «СВЕДЕНИЯ О ПЕРСОНАЖАХ»). Это тот же R3-egress,
что cycle-2 F1 требовал закрыть.

**Вывод.** D13 **существенно сузил** класс (все не-префиксные существительные, производные
стоплиста, image-объекты, короткие/стоплист-слова — закрыты), но **класс не закрыт**:
G1 `_has_person_intent` реализован через `token.startswith(stem)` по
`_PERSON_INTENT_STEMS = ("выгляд","портрет","внешн","фото","фотограф","сним","досье")`
(`image_context_memory.py:138,342-343`), поэтому **любое** существительное, начинающееся с
`фото`/`сним`/`портрет` (открытое семейство: фотон, фотоаппарат, фотография, фотомодель,
снимок, портретист, …), ложно удовлетворяет G1; после G2 (alias-имя найдено в roster) оно
становится `resolved` и читает чужое досье. Дополнительно `_PERSON_INTENT_ABOUT` (`о`/`об`/`про`,
`:141`) срабатывает на **любой** standalone-предлог, а не на «про <человека>» (спец. §3.1:
«`про <токен>`/`о <токен>`/`об <токен>`»). Итог: утверждение spec §3.1 «класс-инвариант: голый
generic-запрос … **не может** разблокировать персонализацию **независимо** от лексикона» —
для префиксного семейства **ложно**. Repo-тест
`TestCorroborationGateD13::test_class_closure_new_noun_bare` (Барракуда/Гироскутер/Синтезатор)
не ловит этот срез: ни одно из слов не начинается с person-intent-стема (слепое пятно покрытия).

## C3.2. Все prior repros — независимый прогон (собственные fakes)

- **Cycle-2 (6):** Тигр/Роза/Панда/Зайка/Ромашка/Лисичка + соответствующие «нарисуй …» →
  все `context_required=False`, `empty_reason="no_person_intent"`, `fact_calls=0`. ✔
- **Cycle-1 (3):** Кот/Лис/Малыш → `context_required=False`, `empty_reason="unknown_person"`,
  `fact_calls=0`. ✔
- Repo-классы `TestAliasCollisionGuard` + `TestCorroborationGateD13` — зелёные (см. C3.6).

## C3.3. Positive path / ambiguous / G2-unavailable

| Случай | Результат |
|---|---|
| `{"7":"Сергей"}` + «нарисуй как выглядит **Сергея**» (склонение) | resolved, facts прочитаны ✔ |
| `{"7":"Лёха"}` + «Нарисуй **Лёху в образе** самурая» (склонение + фраза «в образе») | resolved, facts ✔ |
| `{"1":"Сергей","2":"Сергей"}` + person-маркер, оба в roster | `ambiguous`, candidates `[1,2]`, `fact_calls=0` (0 чтений досье, нейтральный арт) ✔ |
| G2-ридер недоступен (`get_persona_names` отсутствует) | fail-open `none`/`unknown_person`, `fact_calls=0` ✔ |
| `{"7":"Оля"}` + «как выглядит Олю» (<4, G0) | `unknown_person`, facts=0 (false-negative, принято) ✔ |
| `{"7":"Лёв"}` + «как выглядит Льва» (<4, G0) | `unknown_person`, facts=0 ✔ |
| G3-негатив: `{"7":"Акула"}` + «акулу **в образе** самурая» (G2 прошёл) | `no_person_intent`, facts=0 ✔ |
| G3-негатив: `{"7":"Феникс"/"Дельфин"/"Кактус"/"Тигр"}` + person-маркер | `no_person_intent`, facts=0 ✔ |
| G0-негатив: `{"7":"Малыш"}` (стоплист) + person-маркер | `unknown_person`, facts=0 ✔ |
| `{"7":"Сергей"}` + «нарисуй **внешность** Сергея» (легитимный маркер) | resolved, facts ✔ |

Т.е. позитивы и неоднозначность работают; G3 реально блокирует **явно лексиконные** объекты
даже при person-маркере. Проблема — не G2/G3, а ложные G1-срабатывания (C3-H1).

## C3.4. F2 adjudication (важно) + interpretation 7

**Оригинальный cycle-1 F2-сценарий — голый (без person-маркера), прогнан независимо**
(alias `{"1":"Петя"}` + unknown «Лёха», `maybe_handle_keyword`, monkeypatch `run_image_request`):
`«Бот, нарисуй Лёху, нужно точное сходство»` →

- `context_required=False`, `exact_likeness=True`, `empty_reason="unknown_person"` (D13: не персонализировать — корректно);
- reply-блок **содержит** запрос фото/референса и дисклеймер «художественная интерпретация, а не
  документальный портрет»; `_memory_reply_note` возвращает полный текст; промпт = `extract_prompt`
  (A3-parity), «очки» в промпте нет, досье не читалось.

**Вывод:** F2 **остаётся закрытым**; гейт `context_required OR exact_likeness`
(`image_generation.py:1412`, `tool_router.py:328`) и `exact = _detect_exact_likeness(...)`,
вычисляемый **до** разрешения (`image_context_memory.py:714`), делают exact-интент независимым
от `resolved`. **Interpretation 7 верна:** в repo-тесте person-маркер добавлен только к
`test_exact_likeness_resolved_note_regression` (это следствие D13: разрешённый позитив теперь
требует маркера), а **неразрешённый** F2-тест `test_exact_likeness_unresolved_note` остался
**голым** (`:867`) и зелёный. Регрессии F2 нет; отдельного «потерянного» теста нет.

## C3.5. N1 / N3 / F2-retained

- **N1:** `TestSection37` (6) — инъекции через факт/slice/dossier/preferences ассертят структуру
  (DATA-метка, отсутствие `system`, `startswith("ЗАПРОС:")`). ✔
- **N3:** `TestKillSwitch::test_a4_off_no_memory_reads_at_all` спайит `db.fact_calls == []` **и**
  `mem.calls == []`. ✔
- **F2-retained:** `TestExactLikenessGate` (4) — зелёный. ✔

## C3.6. Spec conformance

- **Порядок G0→G1→G2→G3 соответствует spec §3.1:** G0 — в `_resolve_subject`/`_alias_stems`
  (eligibility до шлюза); `_corroborate_subject` (`:420`) делает G1 → G2 (`_persona_names`) → G3
  (`_candidate_is_image_object`). G3 применён **после** G2 — как и требует spec. Расхождения
  порядка нет. ✔
- **Заглавная буква:** `_words` casefold-ит токены, поэтому «только заглавная» G1 не
  удовлетворяет (`test_capitalized_token_alone_not_person_intent` и мой probe). ✔
- **Расхождение набора G1 (Medium, C3-M1):** spec §3.1 перечисляет среди G1-маркеров
  **`похож/похожа`**, но в коде их **нет** ни в `_PERSON_INTENT_TOKENS:124`, ни в
  `_PERSON_INTENT_STEMS:138` (слово `похож` встречается только в `_EXACT_LIKENESS:80-81`).
  Probe: `{"7":"Сергей"}` + «нарисуй похожего на Сергея» / «нарисуй Сергея, как похож» →
  `no_person_intent`, facts=0 (ложный негатив: человек-интент не распознан). Направление —
  over-blocking (не утечка), поэтому Medium, но это отклонение от принятого amended-spec.
- **G1 over-broad (High, C3-H1):** `startswith`/предлоги — см. C3.1; spec §3.1 говорит о
  **закрытом** наборе маркеров, а не о префиксах произвольных существительных.

## C3.7. Checks performed (собственные прогоны ревьюера)

| Проверка | Команда | Результат |
|---|---|---|
| A4 suite | `pytest tests/test_image_context_memory_round1026.py -q` | **67 passed** |
| Focused (Section37+KillSwitch+ExactLikenessGate+CorroborationGateD13+AliasCollisionGuard) | точечно | **39 passed** |
| §104 AST-гейт | `pytest tests/test_unified_image_request_round1026.py::TestBoundsA3 -q` | **7 passed** |
| Полный регресс | `pytest -q` | **9280 passed / 0 failed**, 1 warning (154.63 с) |
| JS | `node tests/js/*.js` (последовательно) | **PASS=47 / FAIL=0** |
| Каталог | REGISTRY/Settings/GROUPS/_TAB_BY_GROUP/TAB_RULES | **470 / 427 / 445 / 101 / 99 / 21** (470/427/101/99/21 — прямым probe; 445 — зелёным `test_catalog_counts_unchanged` в полном прогоне) |
| Канон | `TOOL_CALLING_TOOLS` | **12**, хвост `get_user_context`, нет `request_reference`/`portrait` |
| Версия | `APP_VERSION` | **2.58.30** (без bump) |
| Пробелы/CRLF | `git diff --check` | exit **0** (только LF→CRLF warning'и) |
| Scope creep | grep A4-маркеров вне санкции | только `config/settings.py`, `services/{image_context_memory,image_generation,tool_router}.py`, новый тест (+ `tests/test_unified_image_request_round1026.py` = §104-гейт A3). Новых файлов/маркеров вне scope нет |
| Spec-Hash | SHA-256 `spec.md` | `63064ccb…` — совпадает ✔ |

## C3.8. Blocking findings

### C3-H1 — HIGH. G1 (person-intent) ложно срабатывает на префиксные существительные и предлоги → остаточный egress чужого досье по **голому** generic-запросу

- **Location:** `services/image_context_memory.py:138` (`_PERSON_INTENT_STEMS`),
  `:141` (`_PERSON_INTENT_ABOUT`), `:342-343` (`token.startswith(stem …)` в `_has_person_intent:328`).
- **Requirement/invariant:** amended spec §3.1 класс-инвариант («голый generic image-запрос
  «нарисуй <существительное>» **не может** разблокировать персонализацию независимо от того,
  входит ли существительное в какой-либо лексикон, т.к. G1 требует явной ссылки на человека»),
  SC-A4-09 (amended), REQ-A4-09/-02/-08; ADR-1026-19 D13 («G1 … закрывает класс; новая
  image-лексема утечку не открывает»). Инвариант 1/2/6/14 из §5.
- **Evidence (воспроизводимо, собственный probe):** alias `{"7":"Фотон"}`, roster `["Фотон"]`,
  запрос `«Бот, нарисуй фотон»` → `context_required=True`,
  `resolved_subjects=[{user_id:7, name:"Фотон", resolution:"resolved"}]`,
  `db.get_user_context_facts` вызван, и факт «носит очки и бороду» присутствует в
  `build_final_prompt`. Аналогично: `Фото`/«нарисуй фото», `Фотоаппарат`, `Фотография`,
  `Фотомодель`, `Снимок`, `Портретист`, `Досье`; а также `Кварк`+«… про космос»,
  `Закат`+«… про море», `Город`+«… об огнях» (см. C3.1). Repo-тесты этого не покрывают
  (`test_class_closure_new_noun_bare` использует только не-префиксные слова).
- **Impact:** любой участник, чей alias — существительное, начинающееся с `фото`/`сним`/
  `портрет` (открытое семейство), «захватывается» как субъект чужим голым image-запросом; его
  приватные визуальные факты читаются и уходят во внешний генератор. Это ровно R3-core
  риск (T1/T3), который D13 должен был закрыть; spec-класс-инвариант фактически нарушен.
- **Corrective action (минимум, без смены дизайна):** сделать G1-матчинг **точным/closed-set**,
  а не префиксным: сопоставлять токены с явно перечисленными формами маркеров (и их
  безопасными словоформами), а не `startswith`; `про/о/об` учитывать только как
  «предлог + следующий токен-человек» либо исключить одиночный предлог как самостоятельный
  маркер. Добавить регресс-тесты на префиксное семейство (фотон/фотоаппарат/фотография/
  снимок/портретист/досье) и на предлог-фантом. Пересмотреть `test_class_closure_new_noun_bare`,
  добавив слова, начинающиеся с person-intent-стемов.
- **Verification:** новые тесты + `pytest tests/test_image_context_memory_round1026.py -q` +
  `TestBoundsA3` (7) зелёные; повтор моего probe (ожидается `context_required=False`,
  `fact_calls=0` для всех входов C3.1).

### C3-M1 — MEDIUM (spec-conformance). G1 не реализует маркер `похож/похожа` из amended spec §3.1

- **Location:** `services/image_context_memory.py:124-141` (`_PERSON_INTENT_TOKENS`/`_PERSON_INTENT_STEMS`).
- **Requirement:** spec §3.1 G1 (закрытый набор: «… `знакомый/знакомая`, **`похож/похожа`**»).
- **Evidence:** `{"7":"Сергей"}` + «нарисуй похожего на Сергея» / «нарисуй Сергея, как похож» →
  `empty_reason="no_person_intent"`, `fact_calls=0`; в коде `похож` присутствует только в
  `_EXACT_LIKENESS`, не в G1.
- **Impact:** запросы с легитимной person-ссылкой через «похож/похожа» не персонализируются
  (ложный негатив). Утечки нет (направление over-blocking), поэтому Medium, а не High.
- **Corrective action:** добавить `похож/похожа` (и безопасные формы) в G1-набор — либо
  явно реконсилировать spec. Добавить позитивный тест.
- **Verification:** позитивный тест + A4 suite + `TestBoundsA3`.

## C3.9. Material progress vs cycle 2 (обязательная оценка)

**Материальный прогресс ЕСТЬ.** Cycle-2 дефект был класс-широким: **любое** 4+ символьное
не-стоплистное существительное (Тигр/Роза/Панда/Зайка/Ромашка/Лисичка, + производные
стоплиста) открывало egress. D13/G0–G3 закрывают этот широкий класс: все проверенные
не-префиксные существительные, производные, короткие и стоплистные слова, а также явно
лексиконные объекты при person-маркере — блокируются; 9/9 prior repros закрыты; позитивы,
склонения, ambiguous и G2-fail-open работают. Остаточный дефект C3-H1 — **узкая
реализационная over-generalization G1** (префиксный матчинг + одиночный предлог), а не
возврат к класс-широкой дыре. Поэтому это **не** «три цикла без прогресса»: root-cause D13
сработал, но фикс G1 неполон. Рекомендуемый следующий шаг — **cycle-4 build-fix** (точечно
G1), **не** escalation.

## C3.10. Non-blocking debt / unavailable

- **C3-N1 (Low):** `_PERSON_INTENT_ABOUT` (`о/об/про`) как самостоятельный маркер — источник
  ложных G1-срабатываний; устранить вместе с C3-H1.
- **Unavailable:** живой egress-тест во внешний генератор (провайдер) не выполнялся — egress
  доказан по содержимому `build_final_prompt` (tail факта присутствует), не сетевой доставкой.
  Для EPIC_ONLY приемлемо; фактическая доставка промпта провайдеру не верифицирована.
- **Внешнее:** A3 owner-gate `PENDING OWNER VERIFICATION` — A4 его не закрывает (не блокер
  данного gate). PG-таблицы резервов (A5) — вне scope A4.

## C3.11. Binding (cycle 3)

- `Reviewed-Commit`: `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- `Working-Tree-Hash`: `3d1d8021f01eaf529d70ac2a85468e958f3e957e99dc5cdbd9fc84e846278f74` (recipe — см. C3.0)
- `Spec-Hash`: `63064ccbd5891bde4082d365e7c52def0e0640529a06f3eaa0fe632e33f840c7`

## C3.12. Verdict cycle 3

**Needs Fixes.** F2 **остаётся закрытым** (в т.ч. на оригинальном голом сценарии) и
подтверждён независимо; N1/N3 закрыты; регресс-числа соответствуют заявленным (9280/0, A4 67,
`TestBoundsA3` 7, JS 47/0, каталог/канон/APP_VERSION/diff-check без изменений). Однако
**D13 не закрывает класс полностью**: воспроизведён реалистичный egress чужого досье по
**голому** generic-запросу для существительных, начинающихся с person-intent-стемов
(`фотон/фото/фотоаппарат/фотография/фотомодель/снимок/портретист/досье`) и через одиночный
предлог (`про/об`) — **C3-H1 (High)**; плюс отклонение от amended spec — нереализованный
маркер `похож/похожа` — **C3-M1 (Medium, conformance)**. Класс-инвариант spec §3.1 и
SC-A4-09/REQ-A4-09/-08 для этих входов не выполняются. Прогресс относительно cycle-2 —
материальный (широкий класс закрыт), поэтому рекомендуется **cycle-4 точечный фикс G1**, а не
escalation. Для cycle 4 повторить: входы C3.1 (pos+neg), 9 prior repros, F2-набор, `TestBoundsA3`,
полный pytest, JS, каталог, `git diff --check`, и заново зафиксировать binding.

@Orchestrator: **feature gate**, решение cycle 3 = **Needs Fixes** (C3-H1 High + C3-M1 Medium).
Материальный прогресс после D13 — да; следующий шаг — cycle-4 build-fix G1 (не escalation).
Machine checkpoint не трогаю; коммиты/деплой/DevOps/Scanner не выполняю.

---

# Cycle 4 (T-3640, повторное ревью после build-fix G1)

- **Feature-ID:** `image-context-memory-round1026` (Эпик 3, Wave 4, раунд 10.26)
- **Risk-Level:** **R3** (без понижения; поверхность egress/приватности остаётся, см. C4-N1)
- **Status:** **Approved**
- **Reviewed-Commit:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- **Working-Tree-Hash (cycle 4):** `5f9ac819d7ce3f15d5d44d0628738d09c67c6088961ca38eedd4288e4af60dfa`
- **Spec-Hash:** `63064ccbd5891bde4082d365e7c52def0e0640529a06f3eaa0fe632e33f840c7` (не изменялся)
- **Gate type:** **feature gate** (не агрегатный эпик-релизный gate).
- **Scope cycle 4:** заявленные закрытия C3-H1 (префиксное семейство + предлог) и C3-M1 (`похож`),
  G3-adjudication (данные `_IMAGE_OBJECT_EXTRA`), свои negative/positive probes, все prior repros,
  F2/N1/N3, полный регресс. История cycle-1/2/3 сохранена выше.

**Recipe `Working-Tree-Hash` (cycle 4; новая, воспроизводимая).** SHA-256 от конкатенации, в порядке:
(1) литерал `REVIEW_MANIFEST_V1\n` → (2) сырые байты `git diff e8646af` → (3) сырые байты
`git status --porcelain` → (4) все **untracked-файлы** (каталоги разворачиваются рекурсивно, полный
список сортируется по относительному пути через `/`; из манифеста явно исключён
`plans/features/image-context-memory-round1026/review-T-3640.md`), для каждого: относительный путь
(utf-8) + `0x00` + сырые байты файла + `0x00` → (5) `sha256(spec.md)` hex (ascii).
Манифест детерминирован (два независимых прогона дают один хэш). Учтено: 35 untracked-файлов,
1 312 992 байт содержимого; diff 573 871 Б; status 3 426 Б. Любая правка кода/spec/untracked-файлов
после этого делает binding устаревшим. Сам файл ревью в манифест не входит (ведётся этим ревью).

## C4.1. Проверки (собственные прогоны ревьюера)

| Проверка | Команда | Результат |
|---|---|---|
| A4 suite | `pytest tests/test_image_context_memory_round1026.py -q` | **90 passed** (cycle-3: 67; +23) |
| Focused (TestBoundsA3+G1ExactMarker+CorroborationGateD13+AliasCollisionGuard+ExactLikenessGate+Section37+KillSwitch+FlagsAndCanon) | точечно | **72 passed** |
| §104 AST-гейт | `pytest tests/test_unified_image_request_round1026.py::TestBoundsA3 -q` | **7 passed** |
| Полный регресс | `pytest -q` | **9303 passed / 0 failed**, 1 warning (156.61 с) |
| JS | `node tests/js/*.js` (пофайлово, 47 файлов) | **PASS=47 / FAIL=0** |
| Каталог | REGISTRY/Settings/categorized/GROUPS/_TAB_BY_GROUP/TAB_RULES | **470 / 427 / 445 / 101 / 99 / 21** (прямой probe) |
| Канон | `TOOL_CALLING_TOOLS` | **12**, хвост `get_user_context`, нет `request_reference`/`portrait` |
| Версия | `APP_VERSION` | **2.58.30** (без bump) |
| Пробелы/CRLF | `git diff --check` | exit **0** (только LF→CRLF warning'и) |
| Spec-Hash | SHA-256 `spec.md` | `63064ccb…` — совпадает ✔ |
| Scope creep | grep A4-маркеров (`IMAGE_CONTEXT|image_context|image-ctx|memory_context|context_required`) в tracked-исходниках | только `config/settings.py`, `services/image_generation.py`, `services/tool_router.py` (+ untracked helper/tests). `direct_chat_service.py` пробрасывает `aliases/db/memory` без A4-маркеров; A5/A6/A7-исходники не тронуты |

## C4.2. C3-H1 — независимое закрытие (свои fakes, реальный `build_image_memory_context`)

Метод: собственные fakes (не repo-фикстуры), alias `{"7": <X>}` + `get_persona_names=[<X>]`
(precondition утечки максимально благоприятен), подтверждённый факт «<X> носит очки и бороду».
`facts` = число вызовов `db.get_user_context_facts` (0 = утечки нет).

**A. Префиксное семейство (8 обязательных входов):**

| alias | запрос | context_required | empty_reason | facts | prompt=A3-parity |
|---|---|---|---|---|---|
| Фотон | «Бот, нарисуй фотон» | False | no_person_intent | 0 | ✔ |
| Фото | «Бот, нарисуй фото» | False | no_person_intent | 0 | ✔ (G3: matched=«фото») |
| Фотоаппарат | «Бот, нарисуй фотоаппарат» | False | no_person_intent | 0 | ✔ |
| Фотография | «Бот, нарисуй фотографию» | False | no_person_intent | 0 | ✔ |
| Фотомодель | «Бот, нарисуй фотомодель» | False | no_person_intent | 0 | ✔ |
| Снимок | «Бот, нарисуй снимок» | False | no_person_intent | 0 | ✔ (G3: matched=«снимок») |
| Портретист | «Бот, нарисуй портретиста» | False | no_person_intent | 0 | ✔ |
| Досье | «Бот, нарисуй досье» | False | no_person_intent | 0 | ✔ (G3: matched=«досье») |

**B. Предлог (обязательные 3 + собственные варианты):** Кварк+«…кварка про космос», Закат+«…закат
про море», Город+«…город об огнях», а также Кварк+«…про погоду», Закат+«…о политике»,
Город+«…про работу» → все `context_required=False`, `no_person_intent`, `facts=0`, `roster=0`,
prompt=A3-parity. ✔

**C. Собственные НОВЫЕ кандидаты открытого семейства (проверка, что exact-set не обходится
производным словом):** Портретно/«портретно», Досьешник/«досьешника», Снимочек/«снимочек»,
Внешностьки/«внешностьки», Фоточка/«фоточку», Снимочный/«снимочный», Портретница/«портретницу»,
Выглядик/«выглядик», Фотографка/«фотографку», Досьешный/«досьешный»,
Фотогеничность/«фотогеничность» → все `False`, `no_person_intent`, `facts=0`, prompt=A3-parity.
Стем-матчинг `_stem(token)==_stem(marker)` не даёт префиксных ложных срабатываний. ✔

**Вывод C4.2:** C3-H1 **закрыт** на всех 8 обязательных входах, на 3 предлогах и на собственных
производных кандидатах. Прежний `token.startswith(stem)` (открытое семейство) устранён.

## C4.3. C3-M1 — маркер `похож/похожа` (позитив + склонения)

`_has_person_intent` (unit): `похож / похожа / похожий / похожего / похожей / похожие / похожих /
похожему / похожим / похожую / похожи / «похоже на»` → **True**; e2e alias `{"7":"Лёха"}` +
«нарисуй человека, похожего на Лёху» → `resolved`, uid=7, facts прочитаны. ✔
Мелкое замечание: «похожая» → False (стем «похожа» не совпал с «похож»); направление — over-block,
не утечка (см. C4-N2).

## C4.4. Позитивы маркеров/склонений не перетянуты (false-negative сверх §24)

alias `{"7":"Лёха"}` + запросы: «как выглядит Лёха», «портрет Лёхи», «портрета Лёхи»,
«внешность Лёхи», «внешности Лёхи», «лицо Лёхи», «фото Лёхи», «досье Лёхи», «Лёху в образе самурая»,
«образ Лёхи» → все `context_required=True`, `resolution=resolved`, facts прочитаны. ✔
Т.е. exact-set + G3-данные не сломали spec-позитивы; цена — только узкие false-negative
(см. C4-N2), допустимые §24.

## C4.5. G3-adjudication (правка данных `_IMAGE_OBJECT_EXTRA`)

- **Что делает G3 (проверено по коду и поведению):** `_candidate_is_image_object` вызывает
  `_matched_request_tokens(user_request, aliases, uid)` (`image_context_memory.py:413-421`), который
  возвращает **только токены запроса, чей стем совпал с alias-стемами кандидата**, и блокирует,
  если **все** такие токены классифицированы как image-объект. G3 **не** проверяет «каждое слово
  запроса» — это подтверждает claim Builder'а.
- **Легитимные персональные запросы не сломаны:** `фото Лёхи`, `досье Лёхи`, `портрет Лёхи`,
  `снимок Лёхи` → `resolved`, facts прочитаны (matched-токен — имя «лёхи», а не артефакт). ✔
- **Артефакт-слова как matched-токен блокируются:** bare «нарисуй фото/снимок/досье» с
  одноимённым alias → `no_person_intent`, 0 чтений. ✔
- **Не-артефактные продолжения префиксного семейства G3 не задевают:** `фотографию Лёхи`,
  `фотоаппарат Лёхи` → `no_person_intent` (G1 не находит маркер), утечки/чтений нет. ✔
- **Вывод:** правка `_IMAGE_OBJECT_EXTRA:204-208` (`фото/снимок/снимк/досье`) — **безопасна**,
  минимальна, data-only; логика/порядок G3 не изменены; legit-позитивы сохранены. Claim Builder'а
  «legit-запросы не затронуты» подтверждён независимо.

## C4.6. Residuals adjudication

- **(a) alias «Фотограф» + «нарисуй фотографа» — УТЕЧКА.** `context_required=True`,
  `resolution=resolved`, `fact_calls=1`, `roster_calls=1`, факт «очки и бороду» присутствует в
  `build_final_prompt`. G1 **не** блокирует (стем «фотограф» == маркер-стем «фотограф»), т.к.
  «фотограф» — легитимный G1-маркер из spec §3.1/ADR D13. Обобщение: тот же результат для
  **целого класса** alias, равных generic-person-маркеру: **Друг+«друга», Человек+«человека»,
  Девушка+«девушку», Подруга+«подругу», Мужчина+«мужчину», Женщина+«женщину», Образ+«образ»**
  (все → resolved, facts=1, факт в промпте). Это **C4-N1** (см. ниже) — реальный residual, но
  spec-санкционированный (см. adjudication).
- **(b) «про Сергея» — допустимый false-negative.** alias «Сергей» + «нарисуй что-то про Сергея»
  → `no_person_intent`, `facts=0`; «про/о/об» принимаются только перед человек-местоимением/
  существ. из закрытого набора. Это осознанно консервативное чтение spec §3.1 (утечки нет) —
  **принято** по §24 («отказ важнее неверной персонализации»).
- **(c) Profession/role nouns — утечки НЕТ.** alias Художник/Модель/Архитектор/
  Фотокорреспондент/Скульптор/Дизайнер/Менеджер/Учитель + соответствующий bare-запрос → все
  `False`/`no_person_intent`(или `unknown_person`), `facts=0`. ✔ Единственное исключение —
  «фотограф», потому что это слово включено в G1-набор spec (см. C4-N1).
- **NEW (собственный вывод):** residual сводится к одному правилу — **alias, чей стем совпадает
  с G1-маркером-существительным, на голом generic-запросе даёт персонализацию**. Это следствие
  содержимого Architect-санкционированного G1-набора, а не реализационной over-generalization
  (в отличие от C3-H1).

### C4-N1 — MEDIUM (non-blocking, spec-санкционированный residual / документационный пробел)

- **Location:** `services/image_context_memory.py:131-144` (`_PERSON_INTENT_TOKENS`),
  `:148-166` (`_PERSON_INTENT_MARKER_FORMS`, вкл. `фотограф`), `:372-398` (G1), `:437-441` (G3).
- **Наблюдение/evidence:** alias `{"7": X}` + bare «нарисуй <X-форма>» для X ∈ {Фотограф, Друг,
  Человек, Девушка, Подруга, Мужчина, Женщина, Образ} → `context_required=True`, `resolved`,
  `fact_calls=1`, чужой визуальный факт в промпте (см. C4.6a).
- **Adjudication (почему НЕ блокирует):** слова `друг/подруга/человек/девушка/женщина/мужчина/
  парень` и `фото/фотограф/снимок` **явно перечислены** в Architect-санкционированном G1-наборе
  (spec §3.1, ADR-1026-19 D13). Реализация точно следует spec; residual — свойство принятого
  G1-набора, ограничен admin-сконфигурированным alias (≥4, вне стоплиста) и G2 (нужен
  подтверждённый persona-рекорд). spec §3.1 прямо объявляет полное устранение такого класса
  (через reply/sender-плумбинг) **вне scope A4** («потенциальный follow-up»). Ни REQ-A4-08
  (necessity определена D13 через G1+G2+G3), ни класс-инвариант (он говорит об **image-объектных
  лексемах**, а person-маркеры — не image-объекты) не нарушены по букве принятого spec. Поэтому
  для данного feature-gate это документационный residual, а не дефект сборки.
- **Рекомендация (bounded follow-up, не новый build в A4):** (i) Architect — явно расширить
  «Известный остаточный предел» §3.1 на случай «alias совпадает с person-маркером» (сейчас там
  описан только «объектная лексема + person-маркер»); (ii) опционально — минимальный follow-up
  (по аналогии с C3-H1-фиксом: расширить non-specific-subject cross-check на generic-person-слова
  и `фотограф`, не трогая G1-набор; требуемые позитивы `портрет/фото/досье X` при этом сохраняются,
  т.к. matched-токен — имя). **Если** Architect/owner решит, что класс обязан быть закрыт внутри
  A4, gate следует пересмотреть; текущее решение — approve с эскалацией на архитектурное решение.
- **Verification для follow-up:** новый negative-тест `{«7»:«Друг»}`+«нарисуй друга» →
  `context_required is False`, `fact_calls==[]`; A4 suite + `TestBoundsA3`.

## C4.7. Non-blocking debt (bounded)

- **C4-N2 (Low, test-strength/UX):** over-tightening false-negative сверх §24: «нарисуй фотографию
  Лёхи», «покажи фотку Лёхи», «личико/облик/физиономию Лёхи» → `no_person_intent` (нет в closed-set);
  «похожая» → False. Утечки нет; §24 допускает false-negative. Рекомендуется (follow-up) добавить
  безопасные формы «фотографи»/«фотк» и «похожая», если PM/владелец сочтёт цену приемлемой.
- **C4-N3 (Low, maintainability):** `_stem` (`:262-268`) трактует `й` как удаляемый падежный
  гласный, из-за чего возникают случайные коллизии стемов (напр. «похожей»→«похоже» случайно
  покрывает «похожее»). Не утечка; зафиксировано для будущего ревью.
- **Унаследованные (не переоцениваются, остаются Low):** N1/N2/N4/N5 из cycle-1 — по-прежнему
  не блокируют; N1/N3 подтверждены закрытыми (тесты `TestSection37` 6 и
  `test_a4_off_no_memory_reads_at_all`).

## C4.8. Prior findings / приёмка — остаются закрытыми

- **C3-H1 (High) — закрыт** (C4.2: 8 префиксных + предлоги + свои производные).
- **C3-M1 (Medium) — закрыт** (C4.3: `похож` в `_PERSON_INTENT_MARKER_FORMS`).
- **F2 — остаётся закрытым:** `TestExactLikenessGate` (4) зелёный; гейт
  `context_required OR exact_likeness` не тронут cycle-4.
- **N1/N3:** `TestSection37` (6), `TestKillSwitch` incl. spy-assert — зелёные.
- **9 исходных repros:** cycle-1 (Кот/Лис/Малыш) → `unknown_person`, 0 чтений; cycle-2
  (Тигр/Роза/Панда/Зайка/Ромашка/Лисичка) → `no_person_intent`, 0 чтений; D13-класс
  (Барракуда/Гироскутер/Синтезатор) → `no_person_intent`, 0 чтений. ✔
- **§104/канон/каталог/DDL/kill-switch/OFF-паритет** — без изменений; `TestBoundsA3` 7/7.

## C4.9. Материальный прогресс (обязательная оценка)

**Прогресс сильный.** Cycle-3 дал два блокера: класс-широкий префиксный false-intent (High) и
нереализованный spec-маркер `похож` (Medium). Cycle-4 закрывает **оба** точно и узко: переход на
closed-set exact/stem-equality убирает открытое префиксное семейство, консервативное правило
предлога убирает «про <тему>», добавлен `похож`, а G3-данные закрывают bare-коллизии с
артефакт-словами без ущерба позитивам. Подход концептуально тот же (D13: alias→candidate,
G1/G2/G3), но G1 теперь соответствует spec-набору, а не `startswith`. Новый residual C4-N1 —
**отдельный**, spec-санкционированный, узкий (alias = person-маркер), и не является возвратом к
класс-широкой дыре. Это **не** «четвёртый цикл без прогресса»; оснований для Architect root-cause
по эскалации нет — residual вынесен как bounded follow-up/эскалация на архитектурное решение.

## C4.10. Unavailable / external

- Живой сетевой egress во внешний генератор (реальный провайдер) не выполнялся: egress доказан по
  содержимому `build_final_prompt` (tail факта присутствует), не сетевой доставкой. Для EPIC_ONLY
  приемлемо; фактическая доставка промпта провайдеру не верифицирована.
- A3 owner-gate `PENDING OWNER VERIFICATION` — внешний, A4 его не закрывает (не блокер данного gate).
- PG-таблицы резервов (A5) — вне scope A4.

## C4.11. Binding (cycle 4)

- `Reviewed-Commit`: `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- `Working-Tree-Hash`: `5f9ac819d7ce3f15d5d44d0628738d09c67c6088961ca38eedd4288e4af60dfa` (recipe — C4, выше)
- `Spec-Hash`: `63064ccbd5891bde4082d365e7c52def0e0640529a06f3eaa0fe632e33f840c7` (spec/ADR не менялись)

## C4.12. Verdict cycle 4

**Approved.** Обе линзы пройдены независимо. **C3-H1 закрыт** (8 префиксных входов + предлоги +
собственные производные кандидаты — всё без персонализации/чтений), **C3-M1 закрыт** (`похож`),
позитивы и склонения сохранены, **G3-правка данных безопасна** (legit `фото/досье/портрет/снимок X`
резолвятся; блокируется только bare-совпадение с артефакт-словом). Регресс полностью сходится:
A4 **90/0**, focused 72, `TestBoundsA3` **7/0**, полный pytest **9303/0**, JS **47/0**, каталог
**470/427/445/101/99/21**, канон **12**, `APP_VERSION 2.58.30`, `git diff --check` 0, scope без
расширения. Подтверждённый residual **C4-N1** (alias = generic person-маркер → персонализация на
голом запросе) — **spec-санкционированный** (G1-набор задан Architect в §3.1/D13), ограничен G2 и
admin-alias, и прямо отнесён spec к вне-scope follow-up; **не блокирует** feature-gate, но вынесен
на архитектурное решение/документное уточнение (C4-N1). **feature gate Approved — ready for
reconcile/archive; deployment DEFERRED_TO_EPIC.**

@Orchestrator: **feature gate**, решение cycle 4 = **Approved**; binding —
`Reviewed-Commit e8646af`, `Working-Tree-Hash 5f9ac819…`, `Spec-Hash 63064ccb…`; R3 сохранён;
residual C4-N1 передан Architect как bounded follow-up (не build-блокер). Machine checkpoint не
трогаю; коммиты/деплой/DevOps/Scanner не выполняю.
