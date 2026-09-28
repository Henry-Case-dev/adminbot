# prompt-map-audit.md — карта 6 prompt-ключей (T-3964) + прод-верификация effective values (T-3965)

- **Feature:** `mca-asap21-summary-quality-ui-cleanup`
- **T-3964:** карта по actual execution path (факты кода, baseline 2.58.33, HEAD `8663214`).
- **T-3965:** прод-верификация 28.09.2026, read-only (SELECT-only asyncpg к прод-PG через
  `POSTGRES_DSN` сервера `198.46.175.136:/var/www/admin_bot/.env`; тот же доступ, что
  DevOps-ранбук ASAP-2 deployment.md §4 probe). Целевой чат: PERMsoc `-1002661910336`
  (тот же, что смоук ASAP-2). **R17 соблюдён: содержимое промптов и DSN нигде не печатались
  и не сохранялись — только sha256-префиксы и длины.**
- Метод классификации: sha256(raw) сверялся с локально посчитанной картой канон-констант
  и всех PREV-слепков (`services/summary_prompts.py` @2.58.33); дополнительно проверена
  CRLF-нормализация (совпадений не дала — это НЕ артефакт переносов строк).

## 1. Карта ключ → runtime stage (T-3964, по коду)

| # | Key | Runtime-стадия | Контур | Чтение (файл:строка @2.58.33) | Цепочка effective | UI-имя сегодня (каталог) |
|---|---|---|---|---|---|---|
| 1 | `prompts.summary_l1_clusterizer_system_prompt` | Hybrid L1 «Кластеризатор» (структурирует, не пишет текст) | Hybrid, primary | `summary_l1_clusterizer.py:719–720` (`resolve_prompt`) | hot(PG global) → код-канон R1027 | «Кластеризатор саммари (L1)», stage=synthesizer |
| 2 | `prompts.summary_l2_writer_system_prompt` | Hybrid L2 «Писатель» — **пишет текст текущей Hybrid-статьи** | Hybrid, primary | `summary_l2_writer.py:897–898` (`resolve_prompt`) | hot → код-канон R1027 | «Писатель саммари (L2)», stage=synthesizer |
| 3 | `prompts.summary_system_prompt` | Legacy single-call (OFF-путь и LEVEL-3) | Legacy fallback | `summary_generator.py:685–686` (`hot.get` + `replace("{max_symbols}")`) | hot → код-канон R1021(+A/B блоки) | «Системный промпт саммари», без stage |
| 4 | `prompts.summary_editor_system_prompt` | Legacy Stage-1 «Редактор» (Markdown-выжимка) | Legacy two-call | `summary_generator.py:1754–1757` (`resolve_prompt`) | hot → код-канон R1023-F6/hotfix4 | «Синтезатор саммари (Редактор)», stage=synthesizer |
| 5 | `prompts.summary_narrator_system_prompt` | Legacy Stage-2 «Рассказчик» (kill-switch `SMART_VERBALIZER_MODES_ENABLED` → `PREV_SUMMARY_NARRATOR_R1023`) | Legacy two-call | `summary_generator.py:1794–1797` (`resolve_prompt`) | hot → код-канон R1023+TYPOGRAPHY | «Вербализатор саммари (Рассказчик)», stage=verbalizer |
| 6 | `prompts.summary_cover_style` | «Стиль обложки» (оба контура) | Cover | `summary_generator.py:2069–2090` (`_resolve_cover_style_text`: chat_params → hot → `resolve_cover_style`) | **per-chat capable, уже реализовано** | «Стиль обложки», advanced, без stage |

Ключевых дублей «два UI-пункта → один runtime key» НЕТ (все шесть — разные runtime-стадии;
объединение запрещено §8:3046). Реальная проблема — ложная лексика стадий `synthesizer`/
`verbalizer` на Hybrid L1/L2 (каталог `param_catalog.py:509–520`) — снимается presentation-слоем
(T-3984, `SUMMARY_PROMPT_META`) и титулами каталога (T-3973), Δ количества = 0.

`per_chat=True` у всех шести — выводимое свойство каталога (`ParamSpec.per_chat`,
`param_catalog.py:119–127`: category ∈ {prompts, limits, flags, reactions, content, memory} ∧ не secret),
НЕ факт чтения. Фактически per-chat в рантайме читается ТОЛЬКО cover style (№6).

## 2. Прод-верификация effective values (T-3965, 28.09.2026)

### 2.1 Глобальный слой (`bot_settings`, hot global) и per-chat (`chat_profiles.chat_params.overrides`, PERMsoc)

| Key | Global (bot_settings) | sha256-12 (raw) | len | Класс | Per-chat (PERMsoc) |
|---|---|---|---|---|---|
| `…l1_clusterizer_system_prompt` | есть | `8237880de15f` | 3778 | **custom** (≠ канон 3702, ≠ все PREV; CRLF-нормализация не совпадает) | отсутствует |
| `…l2_writer_system_prompt` | есть | `c913a4b4c53d` | 3110 | **custom** (≠ канон 3057, ≠ все PREV) | отсутствует |
| `…summary_system_prompt` | есть | `67344524cd16` | 3578 | **custom** (≠ канон 3522) | отсутствует |
| `…editor_system_prompt` | есть | `14ae80070e29` | 2063 | **custom** (≠ канон 2023) | отсутствует |
| `…narrator_system_prompt` | есть | `58c9d4237eaa` | 1693 | **custom** (≠ канон 1655) | отсутствует |
| `…summary_cover_style` | есть | `faed624c9d0b` | 33 | **custom** (≠ дефолт 31) | **есть**, custom, len 110 (sha256-12 `35013bd88081`) |

Классификация: «custom» = не байт-в-байт равен ни текущему код-канону, ни какому-либо
`PREV_*`-слепку (`R1021/R1022/R2020` для summary; `R1023/R1023_F3/R1023_F6/R1025_HOTFIX4`
для editor; `R1023` для narrator; `R1026/R1027` для L1/L2), ни их CRLF-нормализованным/strip-
вариантам. Длины custom-значений = канон + небольшие дельты (+33…+76) — правки владельца
поверх канона (genuinely-custom, не слепки).

### 2.2 Ответ на вопрос Q10 (факт)

**Effective runtime prompt, реально управляющий Hybrid L2 prod-output:**
`prompts.summary_l2_writer_system_prompt` из **глобального PG (`bot_settings`), значение —
genuinely-custom владельца** (sha256-12 `c913a4b4c53d`, 3110 симв.), НЕ код-канон R1027.
Гипотеза §11 («code default уже R1027, но prod = старая канон-версия или custom») —
**подтверждена в варианте custom**. Код-канон R1028 (T-3977/T-3980) сам по себе НЕ изменит
prod-поведение, пока PG-значение custom.

### 2.3 Per-chat mismatch (spec расхождение 11) — факт и решение по (h)

- Факт: per-chat-значений stage-ключей (№1–№5) в `chat_params.overrides` чата PERMsoc
  **НЕТ**. Единственный per-chat prompt на проде — `prompts.summary_cover_style`, который
  рантайм уже читает per-chat (`_resolve_cover_style_text`). Рабочий сценарий «пользователь
  правит stage-промпт в контексте чата — поведение не меняется» на проде **не реализован
  данными** (правки в PG лежат глобально).
- Решение по условному фиксу (h) spec Q10: **НЕ применяется** — условие («аудит найдёт
  per-chat-значения stage-ключей») не выполнено. По spec Q10/(h): «Если per-chat-значений
  на проде нет — цепочка документируется без правки кода». Δ каталога = 0, `run_l1`/`run_l2`
  не трогаются по этой линии. Metadata-панель Source (T-3984) показывает
  `configSourceLabel` (chat override / global / code default по факту наличия значений —
  глобальный слой честно виден).

### 2.4 Следствия для миграций T-3980 и деплоя (runbook-факты)

1. **Миграции R1027→R1028 не тронут ни один из 6 прод-ключей** — все значения genuinely-custom,
   а контракт (g)/§26 прямо запрещает перезапись custom (`prompt_migrations.py:265–268`).
   Ожидаемый лог при старте 2.58.34: `[prompt_migration] кастом юзера — НЕ трогаем` ×6
   (для миграционных ключей).
2. Следствие для T-3977 (грамматика/голос/typography/emphasis_spans/finale-инструкции):
   в prod-effective L2 (custom) новых инструкций не появится автоматически. Новая
   **детерминированная** часть (typography normalizer, emphasis_spans-канонизация, finale-
   валидация, Rich cut) заработает без промпта — это кодовые гарантии. Prompt-часть
   (стиль-инструкции §15–§18, выбор шиза LLM §21–§25) активируется на проде после того,
   как владелец вернёт ключи к канону (удаление PG-строки → сид канона при рестарте, либо
   ручной reset через UI). Это runbook-шаг деплоя/acceptance (T-3994/T-3996), НЕ код.
3. Legacy Narrator custom содержит унаследованную инструкцию «приписку про шиза добавит код»
   (из старого канона) — после удаления `_ensure_shiz_postfix` код ничего не дописывает;
   кастомный промпт может подавлять шутку на Legacy-пути до reset ключа владельцем.
   Зафиксировано как известное поведение между деплоем и reset (осознанный компромисс
   запрета «молча перезаписывать custom», §26).
4. Сирота-значения prefilter: `bot_settings` содержит ровно 8 строк `summary_filter_*`
   (перечень в evidence T-3973); в `chat_params.overrides` PERMsoc — 1
   (`flags.summary_filter_enabled`). После T-3973 они остаются в БД и безопасно
   игнорируются (читателей нет) — подтверждает откат-безопасность контракта (i).
