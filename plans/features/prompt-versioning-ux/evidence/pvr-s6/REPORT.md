# PVR-S5 (постоянный стандарт) + PVR-S6 (аудит принуждения) — отчёт

Ветка `pv/std`, база `4baccb1d` (evol/impl). Только документы, инструкции и
тесты: продуктовый код, тексты промптов, DDL и поведение сервисов не менялись.

## 1. Что сделано

| Артефакт | Что именно |
|---|---|
| `docs/prompt-versioning-contract.md` | переписан: §1 — дословное постоянное правило владельца (блокер релиза), §3.1 — карта путей записи и честная граница «одной транзакции», §3.2 — таблица релиза с pin, §3.3 — owner baseline как указатель, §3.4 — пагинация без потолка, §3.5 — legacy-провенанс, §3.6 — честные пределы, §5 — три слоя аудита, §7 — фактическое распределение владения, §8 — открытые пункты с владельцами |
| `AGENTS.md` | короткий абзац «Блокер релиза»: новое редактируемое поле без реестра/журнала/UI версий/baseline отклоняется Reviewer'ом; названы аудит-тесты |
| `README.md` | строка runbook: `--force` по промптным ключам (`prompts.*`) не применять |
| `tests/test_prompt_field_audit.py` | новый аудит: поверхность редактирования (слой 1), согласованность `pg_key ↔ block_id`, наличие маршрутов панели версий, страж обхода по всем ключам (слой 3) — 15 тестов |
| `plans/features/prompt-versioning-ux/evidence/pvr-s6/mutations.py` | три мутации, доказывающие, что аудит умеет падать |
| `plans/features/prompt-versioning-ux/evidence/pvr-s6/byte_check.py` | байтовая сверка мемных промптов со снимком PVR-S0/S1 |

## 2. Зафиксированные расхождения документа с кодом (8 из плана §3)

1. §7 «`prompt_factory` — `list_versions`, `diff_revisions`,
   `get_revision_source`» → теперь: `prompt_registry` = объявление,
   `prompt_release_policy` = реализация, `prompt_factory` = тонкие обёртки без
   своей логики активации.
2. «Деплой активирует заводской текст поверх ручных правок» → разделено:
   поверх правок только если у scope **нет** owner baseline; при baseline
   активный текст и чатовый override не трогаются (pin, `factory_superseded_pinned`).
3. «Запись и активация одной транзакцией» → таблица §3.1: верно для единого
   слоя записи, но не для всего HTTP-запроса (непромптные настройки — отдельный
   второй этап; 503 на промптной части).
4. «Аудит проверяет только константы» → три слоя с именами тестов, включая
   `pg_key ↔ block_id ↔ UI-editor ↔ versioned write` и стража обхода.
5. Устаревшее свидетельство «99 блоков / 98 печатей / аудит 50/50» → фактические
   на этом кандидате: 112 блоков, 111 печатей, 102 метки, 39 блоков с `pg_key`
   (38 ключей), 73 code-only; grep-аудит: 294 файла, 69 кандидатов (68 через
   `code_source` + 1 allowlist), 0 вне реестра.
6. «Устаревший chat-override всегда снимается» → снимается только без pin.
7. Не было baseline/пагинации/лимита 50 → добавлены §3.3 и §3.4: keyset-курсор,
   `HISTORY_PAGE_DEFAULT=50` / `HISTORY_PAGE_MAX=200` как размер страницы, все
   версии достижимы; легаси `list_activations(limit=50)` не вызывается путём
   истории (проверено поиском по коду).
8. Второй ограниченный (`HISTORY_MAX_PER_BLOCK=12`) UI истории Speech-раздела →
   описан как замороженный legacy-журнал; витрина Speech читает PG-журнал
   страницами (`SPEECH_HISTORY_PAGE=50`), потолок 12 к новому журналу не
   применяется; откат ищет версию сначала в замороженном журнале, затем в PG.

## 3. Аудит: что проверяется и чем доказано, что он падает

`py plans/features/prompt-versioning-ux/evidence/pvr-s6/mutations.py --repo .`:

```
CAUGHT | A: промпт скрыт в каталоге без альтернативной поверхности | 1 failed
CAUGHT | B: блок документа без pg_doc_field делит pg_key           | 1 failed
CAUGHT | C: страж PromptJournalBypass больше не поднимается        | 1 failed
restored byte-identical: True
post-restore: 15 passed
```

- **A (поле без достижимого редактора).** Мутация: `prompts.search_system_prompt`
  добавлен в `_HIDDEN_CATALOG_PG_KEYS` → поле исчезает из каталога, поверхности
  нет. Ловится `test_every_editable_prompt_has_reachable_surface`.
- **B (`pg_key`/`block_id`).** Мутация: у `core.personality.compact` убран
  `pg_doc_field` → `character.core` делят две обычные записи. Ловится
  `test_shared_pg_key_is_an_explicit_document`.
- **C (обход журнала).** Мутация: `raise PromptJournalBypass` в
  `assert_prompt_write_allowed` заменён на `return` → прямой
  `chat_params.set_chat_params` проходит. Ловится
  `test_guard_rejects_direct_chat_override_write_for_every_prompt`.

Первая версия мутации B (дублирование ключа словаря) оказалась негодной —
литерал словаря молча перезаписывает ключ, поэтому блок исчезал, а не делил
адрес; мутация заменена на потерю `pg_doc_field`.

Дополнительно страж проверяется по **каждому** ключу реестра, а не по одному
мемному: 37 текстовых ключей отвергаются и через `cache.set/set_many`, и через
`set_chat_params`; документ Core — мутацией поля внутри документа; запись
внутри `journal_write_scope` по-прежнему проходит (страж не вакуумный).

## 4. Байтовая проверка мемов

`py plans/features/prompt-versioning-ux/evidence/pvr-s6/byte_check.py --repo .`:

```
initiative.meme.joke:  sha256=2f30ca1f9a6b baseline=2f30ca1f9a6b bytes=95/95  label=meme-joke-evol014  identical=True
initiative.meme.image: sha256=f81fe7e4b505 baseline=f81fe7e4b505 bytes=51/51  label=meme-image-evol014 identical=True
changed since S1 baseline: 1 ['direct.base.l2_writer']
MEME BYTES IDENTICAL: True
```

Единственная дельта относительно снимка PVR-S1 — `direct.base.l2_writer`;
она пришла из уже влитой линии `rc-selfcorr` (`bf62c29a`), не из этого среза:
`git diff 4baccb1d -- services/ web/ config/ scripts/` пуст.

## 5. Прогоны

| Набор | Результат |
|---|---|
| `tests/test_prompt_field_audit.py` | 15 passed |
| + `test_evol018_prompt_audit.py`, `test_prompt_versioning_enforcement.py`, `test_evol012_barrier_retired.py` | 60 passed (вместе с новым файлом) |
| `test_prompt_baseline.py`, `test_prompt_history_pagination.py`, `test_evol016_prompt_activation.py`, `test_evol017_prompt_history_ui.py` | 77 passed, 1 skipped |
| `test_evol016_prompt_journal_v39.py`, `test_prompt_migrations.py`, `test_summary_asap21_prompt_migrations.py`, `test_asap_prompt_history_integrity.py` | 78 passed, 1 skipped |
| Мутационный прогон | 3 × CAUGHT, восстановление байт-в-байт |

Итого по версионным наборам: **215 passed, 2 skipped, 0 failed**.

## 6. Найдено по ходу (не блокирует срез)

- Страж обхода не считает изменением «неправильную форму» значения документа
  `character.core`: запись сырой строки вместо JSON формально не меняет ни
  одного поля. Реальный код так не пишет (все пути идут через
  `write_prompt_values`), но это защита от будущей ошибки. Записано в
  `docs/prompt-versioning-contract.md` §8 п.6 с владельцем PVR-S6-AUDIT;
  тестом **не** закреплено как «ожидаемое поведение».
- Три блока с `scope='code'` при наличии `pg_key` (мемные два и
  `factcheck.critique.directive`) — метаданные противоречат §4 контракта:
  история цела (читается по `block_id`), но карточка называет scope «code».
  Объявлены поимённо в аудите (§8 п.4), исправление — отдельным срезом.
