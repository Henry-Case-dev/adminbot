# PVR-S3 — полная история версий (страницы, стабильный курсор) + N1/N2

- Ветка: `pv/history`, база `44e1e589` (ветка `evol/impl`), срез `PVR-S3-HISTORY`.
- Контракт: `arch/versioning-ux-contract.md` §3 (атомарный слой, `list_versions`),
  §5 (чтение без тел), §2.4 п.9 (retired/несовместимые), §4 (pin).
- ТЗ владельца: `plans/owner_inputs/2026-11-04-epic-prompt-versioning-ux-01.md`
  §2.2 п.3–5 (полный список страницами, источник/автор/область/статус, полный
  текст отдельным запросом), §3.5 (без `HISTORY_MAX`/`LIMIT 50`, stable cursor,
  1000+ отзывчиво), §3.7 (тел в списках нет, RBAC global/чат), §4 (pin).
- Ревью-замечания, закрытые здесь: `reports/pv-s2-review.md` N1 и N2.

## 1. Что изменено

| Файл | Изменение |
|---|---|
| `services/prompt_registry.py` | N1: ветка `pinned` в `activation_plan` поднята ВЫШЕ `not has_import` (cutover), но НИЖЕ no-op рестарта — закреплённый scope нельзя перетереть первым размеченным релизом, а рестарт остаётся истинным no-op |
| `services/prompt_release_policy.py` | N1: снимок текущих байтов вынесен в `_record_legacy_snapshot` и вызывается также в pinned-ветке; N2: `copy_revision_to_global` отдаёт фактически сохранённый `reason`; страничное чтение истории (`list_history_page`, `list_revisions_page`, `list_activations_page`, `find_revision_by_sha`), курсоры, статусы/источники, `reason_text` в `/source` и `/diff`; `list_versions` больше не ограничивает историю |
| `services/prompt_factory.py` | обёртка `list_versions` пробрасывает `page_size`/курсоры |
| `web/api/routes.py` | `GET /api/prompts/{key}/versions`: параметры `page_size`, `cursor`, `revisions_cursor`, `activations_cursor`; 422 на испорченный курсор |
| `web/api/speech.py` | история Speech-раздела читается из ЕДИНОГО журнала страницами (прежний bounded-журнал на 12 — только как честная граница при недоступном журнале); откат находит ревизию по `sha256_12` в журнале и отказывает для retired/несовместимой |
| `tests/test_prompt_history_pagination.py` | новый durable-тест `TEST-LIFECYCLE: CONTRACT` (18 тестов) |

DDL нет, второго журнала/реестра нет, новых LLM-вызовов/бюджетов нет, тексты
промптов не менялись (`tests/test_evol018_prompt_audit.py` не в диффе и зелёный),
старые записи не удаляются.

## 2. Контракт страниц

`GET /api/prompts/{key}/versions?page_size=&cursor=&revisions_cursor=&activations_cursor=`

| Параметр | Смысл |
|---|---|
| `page_size` | размер ОДНОЙ страницы, 1..200; `0`/мусор → 50 (это не лимит истории) |
| `cursor` | непрозрачный keyset-курсор объединённой ленты `entries` (сохранения + активации), новые сверху |
| `revisions_cursor` | курсор списка `revisions` (первая страница — самые новые, внутри страницы порядок ASC) |
| `activations_cursor` | курсор списка `activations` (новые сверху, как в EVOL-017) |

Курсор: `base64url(JSON {"v":1,"t":<created_at UTC ISO>,"i":<вторичный ключ>,"r":<rank>})`.
Условие страницы — строгое `(created_at, sort_id) < (t, i)`: смещения нет, поэтому
вставка новых записей не сдвигает и не дублирует уже показанное. `r` (rank)
переносится курсором, поэтому «порядковый номер» не пересчитывается `COUNT` и не
прыгает при параллельных записях. Вторичный ключ: `revision_id` для ревизий,
`act:%020d` для активаций. Порядок обхода во всех трёх списках — «вглубь истории».

Ответ (аддитивно к прежним ключам):

- `entries[]` — объединённая лента (§2.2 п.3): `entry_type`, `order`, `created_at`,
  `revision_id`, `event_id`, `source` (`manual|imported|from_release|restored|legacy`),
  `source_label`, `origin`, `kind`, `outcome`, `detail_code`, `actor`, `scope`,
  `chat_id`, `status` (`active|baseline|inactive|incompatible|retired`),
  `status_label`, `actionable`, `reason`, `reason_text`, `body_available`, `chars`,
  `sha256_12`, `release_id`, `factory_revision`, `schema_compat`, `retired`.
- `page` — `{page_size, order:"newest_first", next_cursor, has_more, returned, rank_start}`.
- `revisions[]`/`activations[]` — прежние списки, теперь страница + `status`/
  `source`/`actionable`/`reason_text`/`body_available` в каждой строке.
- `revisions_page`/`activations_page` — `{order, (paging), next_cursor, has_more, returned}`.

**Список vs тело.** Ни один список не содержит текста промпта: он либо не
загружается из журнала (PG: `length(body) AS char_count`), либо не попадает в
ответ. `body_available` говорит лишь о том, что тело можно запросить.
Полный дословный текст отдаёт существующий авторизованный
`GET /api/prompts/revisions/{id}/source` (RBAC: ревизия → блок + (scope, chat) →
право просмотра; чатовая ревизия чужого чата → 403). `retired`/несовместимые
читаются и сравниваются (`/source`, `/diff` + `reason_text`, `actionable=false`),
но не активируются и не назначаются базовыми.

## 3. N1 — закреплённый scope и первый размеченный релиз

`activation_plan(..., pinned=True)` теперь возвращает `PLAN_ACTIVATE_PINNED`
даже при `has_import=False`. Значение не пишется, ревизия новой метки уходит в
историю, `factory_revision_applied` двигается → следующий рестарт — истинный
no-op (`PLAN_NOOP`, ноль строк). Снимок текущих байтов сохранён: в pinned-ветке
вызывается тот же `_record_legacy_snapshot` (`legacy_snapshot` /
`legacy_empty`), что и в cutover.

## 4. N2 — провенанс копирования

`copy_revision_to_global` после `ON CONFLICT DO NOTHING` перечитывает ревизию и
возвращает **её** `reason`; при копировании тех же байтов из другого чата ответ
совпадает с журналом (`copied_from_chat:<первый источник>`), а не с текущим
вызовом.

## 5. Тесты

`tests/test_prompt_history_pagination.py` (18 тестов, `CONTRACT`):

1. 1000 ревизий + 200 активаций: обход 12 страницами даёт все 1200 записей ровно
   по одному разу, порядок детерминирован, `page_size` соблюдён, верхняя запись —
   самая новая, обход < 10 c (факт ≈ 0.02 c на in-memory сторе и 3 запроса/страницу
   в PG).
2. Непрерывные `order` 1..50, 51..100; страницы не пересекаются.
3. Стабильность курсора: вставка 5 более новых записей между страницами → вторая
   страница равна срезу исходного снимка `[10:20]`, без дублей и сдвига.
4. Отсутствие тел в ответе (поиск текста в `json.dumps`), `body_available=true`,
   тело приходит только из `/source`.
5. Страницы `revisions`/`activations` без потолка 50 (обход всех 70 + 70).
6. Первая страница `revisions` — самые новые, курсор ведёт вглубь.
7. Источник/автор/область/статус в строке (`from_release`/`manual`/`imported`,
   `baseline`, `active`).
8. retired/несовместимая: `status`, `reason_text`, `actionable=false`, при этом
   `/source` отдаёт тело, `/diff` сравнивает и сообщает причину.
9. Изоляция чатов: история чата A не видна в чате B и не просачивается в global.
10. HTTP: полный обход 150 записей курсором, `422` на испорченный курсор,
    `page_size=0 → 50`, `page_size=1000 → 200` и `has_more=true`.
11. N1: pinned + нет значения + нет маркера импорта → `activate_pinned`,
    значение не записано, ревизия в истории, повтор — no-op.
12. N1: pinned + ручной текст вне журнала → снимок в историю, значение цело.
13. N2: ответ = сохранённый `reason`.
14. Speech: история из журнала, 50 строк при `page_size=50`, `has_more`, прежние
    ключи строки сохранены; bounded-журнал — только при недоступном журнале.

### Мутации (каждая — отдельный прогон, файл восстановлен побайтово)

| Мутация | Результат |
|---|---|
| N1: `pinned` снова ПОСЛЕ cutover | **CAUGHT** — 1 failed |
| N2: отдавать запрошенный `reason` вместо сохранённого | **CAUGHT** — 1 failed |
| Потолок истории: `page_size` урезается до 50 | **CAUGHT** — 1 failed |
| Тело ревизии попадает в список (стор → поле → ответ) | **CAUGHT** — 1 failed |
| Статус игнорирует `retired` | **CAUGHT** — 1 failed |
| Курсор включительный (`<=`) → сдвиг страницы | **CAUGHT** — 1 failed |
| Чат-фильтр отключён (утечка истории чата) | **CAUGHT** — 1 failed |
| Speech-история снова ограничена 12 | **CAUGHT** — 1 failed |

Скрипт повторного прогона: `plans/features/prompt-versioning-ux/evidence/pvr-s3/mutations.py`
(`py -3 mutations.py --repo <корень этого worktree>`; восстанавливает файлы
побайтово и печатает `restored byte-identical: True`).

## 6. Прогоны

| Набор | Итог |
|---|---|
| история/журнал: `test_prompt_baseline`, `test_prompt_history_pagination`, `test_prompt_migrations`, `test_prompt_versioning_enforcement`, `test_evol016_prompt_activation`, `test_evol016_prompt_journal_v39`, `test_evol017_prompt_history_ui`, `test_evol018_prompt_audit`, `test_asap_prompt_history_integrity` | **168 passed, 2 skipped** |
| webapp/speech/мемы: `test_webapp_api`, `test_soul1_w6_speech_ui`, `test_soul1_factory_defaults`, `test_soul1_core_registry_api`, `test_meme_pipeline_api`, `test_evol014_meme_initiative`, `test_p0_persistfix_speech_chat_scope`, `test_initiative_speech_layers_chat_overrides`, `test_meme_joke_speech_layers`, `test_meme_init_diagnostics`, `test_p0_prompts_core`, `test_prompts_round1024`, `test_p0_meme_publication_hotfix`, `test_p0_meme_image_only` | **396 passed** |

Предсуществующих падений в этих наборах нет.

## 7. Ожидания старых UI-тестов

Ни один существующий тест не фиксировал потолок `50` активаций и не фиксировал
второй bounded-журнал `HISTORY_MAX_PER_BLOCK = 12` (проверено поиском по
`tests/`: `HISTORY_MAX_PER_BLOCK`, `limit=50`, `50` в промпт-тестах отсутствуют).
Правки ожиданий поэтому не потребовались; форма строки `revisions`/
`activations` и ключи прежние, изменения аддитивные.

## 8. Что S4 может брать как есть

- `entries[]` + `page.next_cursor`/`has_more` — единственный список для панели
  «История версий»: порядок, источник, статус, причина, доступность тела.
- `status`/`status_label`/`actionable`/`reason_text` — для кнопок и honest-причин
  (`Посмотреть`/`Применить`/`Сравнить`/`Назначить базовой`/`Скопировать`).
- `body_available` + существующий `/source` — тело только по клику.
- `page_size` — менять размер страницы по ширине панели.
- Speech: `history` (прежние ключи) + `history_source`/`history_page`, откат по
  `sha256_12` работает для версий, существующих только в журнале.

Чего S4 НЕ получает: виртуализации и раскладки панели (это его срез), подписи
счётчика `{joke}` и мемных карточек.

## 9. Остаточные риски

- PG-индекс под ключ страниц (`created_at` в `prompt_activations`) не создаётся
  (DDL запрещён). На 1000+ строк в одном блоке keyset-запрос остаётся дешёвым
  (`block_id` ограничивает выборку), но при десятках тысяч активаций одного блока
  потребуется аддитивный индекс — отдельное решение, не в этом пакете.
- Ключ `order` считается из курсора, а не `COUNT`: при «перепрыгивании» страниц
  вручную номера могут расходиться с фактической позицией — это намеренно
  (номера не должны сдвигаться).
- `revisions`/`activations` в ответе теперь страницы: старый UI без S4 видит
  самые новые записи и не листает вглубь; листание реализует S4.
