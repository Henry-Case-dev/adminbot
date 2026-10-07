# RCA — Cover Prompt Transparency (T-5242, lane RCA-P2-cover)

Read-only RCA. Прод: 2.58.67, HEAD `6f062fa` (код локального worktree соответствует
проду — cover-контур в release не менялся с 10.48). Прод-evidence: один SSH-коннект
(journalctl read-only), R17-safe (в логах кода и так нет текстов промптов — только
длины/флаги/hash; секреты не печатались).

## 1. Dataflow: Summary → image-provider (фактический)

### Base Generation (первичная обложка)

```
Summary prose
  → Stage-1 JSON: draft.cover_prompt (EN, ≤300, одна сцена)   system2_handoff.py:87 COVER_PROMPT_MAX=300
  → нормализация ≤300 по границе слова                        system2_handoff.py:91 normalize_cover_prompt
  fallback (draft пуст/нет): ПЕРВОЕ предложение prose, ≤300   summary_generator.py:3474 _derive_fallback_cover_prompt
  → image_prompt = style + " " + visual                       summary_generator.py:282 compose_cover_image_prompt
      style: ≤500 chars (настройка владельца, приоритетно)    settings: SUMMARY_COVER_STYLE_MAX_CHARS=500
      total: ≤1000 chars (переполнение режет visual)          settings: SUMMARY_COVER_PROMPT_MAX_CHARS=1000
  → generate_image_verbose(image_prompt)                      summary_generator.py:2705,2729
  → provider POST (qwen-image-3-pro @ nano-gpt.com)           image_generation.py:1081 generate()
```

Base получает РОВНО две компоненты: `style` + `cover_prompt`. Больше ничего.

### Style Edit (поверх base)

```
cover_prompt (тот же ≤300) -----> summary_text        summary_generator.py:3007 summary_text=cover_prompt
base style (настройка) ---------> base_style_prompt   summary_generator.py:2800-2801
  → brief = brief_from_text(summary_text)             cover_style_jobs.py:1448
      = ПЕРВОЕ предложение уже короткого cover_prompt  image_prompt_compiler.py:143 brief_from_text (≤400)
  → compile_style_prompt                              cover_style_jobs.py:1077
      P0 runtime_invariants (номер выпуска + запрет дублей)  cover_style_jobs.py:1094-1097 — не режется
      P1 style_instruction (профиль, 392 chars)              cover_style_jobs.py:1098
      P1 base_style_prompt                                   cover_style_jobs.py:1101-1104
      P2 references text (описания; у сида их НЕТ)           cover_style_jobs.py:1107-1114
      brief — бюджетная компонента (режется первой)          image_prompt_compiler.py:1115-1117
  → edit_image(prompt, base_image_path, reference_paths)    cover_style_jobs.py:1564 → cover_style_edit.py:358
      images[] = base + references (КАРТИНКИ-инпуты)         cover_style_edit.py:383-385
  → provider 400 prompt_limit_unknown → РОВНО 1 retry        cover_style_jobs.py:1664-1670
      minimal=True: ТОЛЬКО P0+P1 — brief и refs_text         cover_style_jobs.py:1667-1670
      выбрасываются ЦЕЛИКОМ
```

## 2. Вердикты по 7 элементам §0 Cover

| # | Элемент | Вердикт | Куда доходит | Где теряется |
|---|---------|---------|--------------|--------------|
| 1 | Базовый стиль обложки | **CONFIRMED** | Base: приоритетно (style_len=110 на проде, style_present=True во всех прогонах); Style Edit: P1 base_style_prompt | не теряется (кап 500; переполнение режет visual, не стиль) |
| 2 | Сюжет/scene из Summary | **REFUTED** | только как `cover_prompt` ≤300 (draft) или первое предложение фолбэка | Base: это ЕДИНСТВЕННЫЙ смысловой источник; Style Edit: double-squeeze до 1 предложения; при prompt-retry выбрасывается целиком (прод: 911→708) |
| 3 | Контекст финального Summary | **REFUTED** | нигде | `summary_text=cover_prompt` (summary_generator.py:3007); `brief_from_text(cover_prompt)` — second squeeze; в UI-budget `context: 0` захардкожено (cover_styles.py:363) — не баг UI, честное отражение того, что context реально пуст |
| 4 | Дополнительный Style Profile | **CONFIRMED** | Style Edit P1 (instruction 392 chars), не режется даже в minimal-retry | не теряется |
| 5 | Номер выпуска | **CONFIRMED** | P0 runtime_invariants, `issue_present=True` на проде (issue 23, 24) | не теряется |
| 6 | Логотип/roles references | **ADJUSTED** | картинки-референсы доезжают как image-input в ОБОИХ attempts (reference_count=1, 475189 bytes на проде; cover_style_edit.py:383-385, ref_paths при retry не меняются) | текстовые ОПИСАНИЯ ролей отсутствуют по своей природе (сид-референс без description → P2-компонент пуст; cover_style_registry.py:97-99 SEED_FILES только картинка) и в minimal-retry отбрасываются (молча, но их и не было) |
| 7 | Запреты дублей/runtime-инварианты | **CONFIRMED** | P0, не режется никогда (cover_style_jobs.py:1093-1097; image_prompt_compiler.py:26) | не теряется; НО относится только к Style Edit — в Base-генерации инвариантов нет по конструкции |

**Итог по §0:** из 7 элементов реально доходят 1, 4, 5, 7 (полностью), 6 (картинкой, без текстовых ролей). Элементы 2 (в ослабленном виде) и 3 — нет. Сюжетная линия — самое слабое звено обоих этапов.

**Прозрачность («владелец видит В ТОЧНОСТИ что отправилось»): REFUTED.**
- Логи: только `prompt_len`, `prompt_hash` (16 hex), длины компонент, флаги (SAFE_LOG_FIELDS whitelist, cover_style_jobs.py:225+).
- БД: полный prompt НЕ персистится нигде. `MediaJobState` (Base) не имеет поля prompt (media_execution.py, dataclass: operation/provider/model/status/stages); Style Edit персистит только `prompt_diagnostics` (числа/enum) в task_jobs (cover_style_jobs.py:1485-1488).
- API: `GET /cover/test-style/{job_id}` прямо документирует «API keys и полные prompt не отдаются» (cover_styles.py:1371).
- Owner-facing budget preview собирается из draft-компонент (cover_styles.py:337 `_budget`), это оценка, а не фактический sent prompt; после отправки восстановить строку невозможно даже админом.
- Есть hash (`sha256[:16]`), но сверять с ним нечего — эталонной строки не существует.

## 3. Root cause слабого сюжета (механика)

Цепочка из четырёх независимых squeezing-ступеней, каждая легитимна сама по себе:

1. **Контракт cover_prompt = короткий scene seed.** Stage-1 инструктируется на EN ≤300 chars одну сцену (system2_handoff.py:87, docstring `summary_generator.py:3419`). Это осознанный дизайн (F6/T-2485), но с тех пор cover_prompt остался ЕДИНСТВЕННЫМ смысловым источником — контракт §8 («не единственным») не реализован.
2. **Регулярный Stage-1 fallback делает сюжет ещё беднее.** Прод: `reason=draft_cover_empty → prompt_len=44/22/61` (Oct 04 19:03, Oct 05 13:04, Oct 05 19:06) — первое предложение prose, 22–61 chars на весь сюжет base-обложки.
3. **Style Edit double-squeeze.** `summary_text=cover_prompt` (уже ≤300) → `brief_from_text` берёт из него ещё только первое предложение → brief_chars=202 в удачном случае. Итоговый сюжет Styled = подмножество подмножества Summary.
4. **Unknown-limit retry систематически выбрасывает сюжет.** Прод (оба прогона 13:09 и 19:06, повторяемо):
   - `limit_unit=unknown:unknown | limit_source=unknown | capability_state=unknown` — capability-резолв НЕ знает лимит qwen-image-3-pro;
   - attempt 1: `prompt_len=911` (runtime+style392+base110+brief202) → provider отказ `prompt_limit_unknown`;
   - attempt 2: `prompt_len=708` — minimal=True, `brief=None, references нет` (cover_style_jobs.py:1667-1670): 911−708=203 ≈ ровно brief (202 chars).
   Финальную styled-картинку рисует промпт БЕЗ сюжета: «редактируй, сохрани сцену, вот стиль, вот номер выпуска» — а сцена в base могла быть 22 chars. Это прямая механика «сюжет слабый/отсутствует».

Root cause одной фразой: **сюжет не имеет гарантированного бюджета ни на одном этапе** — он P2-по-факту (единственная budget-компонента, image_prompt_compiler.py:1115-1117) и единственная жертва minimal-retry, при этом Summary-context в пайплайн не вводится вообще.

## 4. Прод-evidence (структура, R17-safe)

Один SSH-коннект, journalctl 4 дня, окт 04–06:

- Полные успешные пайплайны `COVER_PIPELINE_DONE status=styled` ×2 (13:09, 19:06 Oct 06), style `medved_press` rev 7, `generate_then_edit`, provider `nano-gpt.com`, model `qwen-image-3-pro`.
- Style SUBMITTED (оба раза идентично): `prompt_len=911 | prompt_hash=<16hex> | reference_count=1 | issue_number=23/24 | reference_bytes_total=475189 | instruction_chars=392 | brief_chars=202 | compiled_chars=911 | limit_unit=unknown:unknown | issue_present=True | edit_route=image_api | limit_source=unknown` → retry `prompt_len=708` → SUCCEEDED (77–86 s, sync).
- Base: `summary cover: prompt composed | style_present=True | style_len=110 | visual_len=22…236 | final_len=133…347 | has_comic=True | has_heading=True` — visual_len (= cover_prompt) скачет 22–236; в fallback-прогонах 22/44/61.
- `[image] generated` — стабильно, 0.7–2.0 MB, 54–88 s.
- Владелец из этих логов НЕ может узнать, ЧТО именно видела модель — только сколько символов и какой hash.

## 5. Направление фикса (одной строкой)

Ввести `CoverPromptManifest` (компоненты source/original/sent/kept|compacted|omitted + final_prompt + prompt_hash + provider/limit) с персистом полного sent prompt (admin-only API, retention = run evidence), передать bounded Summary-context (title+события) и story-minimum в Base и Style Edit, а unknown-limit retry заменить semantic squeeze с обязательным story-минимумом вместо `minimal=True`.

## 6. Incidental findings

- `related-nonblocking`: сид-профиль не имеет reference descriptions → P2-компонент references всегда пуст, `references_chars` в breakdown нулевой; роль reference живёт только в картинке-инпуте и тексте instruction. Не дефект прозрачности, но owner должен знать, что «текстовое описание референса» сейчас не существует как сущность.
- `related-nonblocking`: `_budget` UI (`context: 0`, cover_styles.py:363) — честно, но после появления Summary-context в промпте источник надо синхронизировать с manifest'ом (единый compiler — §10A.1).
- `uncertain`: retry 911→708 сработал за ~2 мс после первого submit (13:09:41,866 → 13:09:45,010 — это ~3.1 s, sync edit-call) — повторяемость 100% (2/2 прогона), но выборка мала; probability = каждый production run при неизвестном лимите.

## 7. Что НЕ менялось

Код, тесты, планы, git-индекс, прод-состояние — не изменялись. Единственная запись — этот файл.
