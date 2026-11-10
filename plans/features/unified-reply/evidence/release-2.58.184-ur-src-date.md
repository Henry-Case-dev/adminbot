# Release 2.58.184 — UR-SRC-DATE (дата публикации веб-источника)

**Release (deployed):** `77a63bc523ce3e5f5537cf11e8d0a3a9737e01f7`, ветка `release/2.58.184` (origin + прод).
**Продуктовый коммит порта:** `5e85f990`. **Линия:** `0fed5845` (2.58.183). **Одобренный кандидат:** `7cf8e169` (ветка `fix/search-source-dates`, база `92070d0e`, 2.58.181).

## Перенос среза

Кандидат базировался на 2.58.181, поэтому перенос сделан combined-diff'ом
`92070d0e..7cf8e169` по файлам самого среза, а не одиночным cherry-pick 7cf8e169:
последний коммит тройки (791e4009 → 82d21889 → 7cf8e169) содержит только правку
предыдущих, и его изолированный cherry-pick давал конфликт «ours deleted / theirs
modified» плюс отсутствующий импорт `services.search_aggregator` в
`direct_execution.py`. Применение combined-diff прошло **без конфликтов**.

Файлов в срезе семь, а не три: кроме `services/search_aggregator.py`,
`services/direct_execution.py` и `tests/test_search_source_dates.py`, коммит
`791e4009` меняет `services/tool_router.py` (компактор выдачи сохраняет дату
отдельным полем, а не в сниппете) и три теста формата строки источника
(`test_rlr_acceptance_rows`, `test_rlr_no_second_author`,
`test_unified_reply_ur_b_search_first`). Без `tool_router.py` срез терял бы часть
одобренного поведения, а три теста гарантированно падали бы на новом формате
пака. Инспектор и память не тронуты.

Идентичность: `tests/test_search_source_dates.py` совпадает с кандидатом
побайтово (sha256 `fa3e3cae73561a1e2c0f4061651483827e3dc6587699c5df2df613153002e2b7`,
как в evidence строки UR-SRC-DATE); `services/direct_execution.py` в рабочем
дереве идентичен версии кандидата.

## Дельта к 0fed5845

33 файла: 7 файлов среза + `config/settings.py` (APP_VERSION), 
`plans/docs/param-registry-round1025.meta.md`, 24 пина версии в тестах.
Других изменений нет.

Не тронуты (блобы совпадают с 0fed5845 и с 92070d0e):
`services/permissions.py` `e20d46eb`, `web/api/avatars.py` `3b8be940`,
`web/api/deps.py` `509b387d`, `services/text_morphology.py` `69775156`,
`services/summary_memory.py` `717236b5`, `services/mca_retrieval_context.py`
`259bc0b4`. Миграций/DDL нет: схема `user_version=47` до и после.

## Предвыкатные проверки (на точном дереве)

| Набор | Результат |
|---|---|
| `tests/test_search_source_dates.py` | 35 passed |
| Факт-чек набор (29 файлов: `test_factcheck_*`, temporal, `test_evol_factcheck_critical`, `test_evol_fc_evidence_style`, ledger, `test_rlr_factcheck_numeric_stage`) | 593 passed |
| Поиск/evidence/direct набор (35 файлов: `test_search_*`, `test_evol_evidence_*`, `test_smartsearch_*`, `test_unified_reply_ur_b_*`, `test_rlr_*`, `test_direct_*`) | 1024 passed, 5 failed |
| ADR-1019 guard `test_scenario19_background_services_have_no_web_imports` | 1 passed |
| После бампа версии (пины + срез + guard) | 91 passed |

Классификация 5 падений: `tests/test_direct_fallback_recompose_asap32.py`
(`TypeError: ... unexpected keyword argument 'sent'` в `services/llm_client.py`)
— воспроизводятся **на чистом 0fed5845** тем же составом (5 failed / 3 passed),
к релизу отношения не имеют, относятся к незавершённой правке fallback-подписи.
Других падений нет.

## Выкат

Прод: `/var/www/admin_bot`, ветка `release/2.58.184` на `77a63bc5`.
Предсостояние: detached HEAD `0fed5845`, `APP_VERSION 2.58.183`, unit `active`,
единственная незакоммиченная запись — `?? .cache/` (вне дельты, перенесена, не
тронута). `git fetch` + `git checkout -B release/2.58.184 origin/release/2.58.184`,
`systemctl restart admin_bot`.

Пост-выкат: `/healthz` → `200 {"status":"ok","version":"2.58.184"}`,
unit `active`, `NRestarts=0`, в журнале за 30 минут нет записей уровня err,
`Traceback`/`CRITICAL` — 0, `APP_VERSION` на сервере `2.58.184`,
`user_version=47`.

## Живая проверка даты (реальные ответы провайдеров, без сообщений в чаты)

Read-only прогон поискового пути на выкаченном дереве:

* **Tavily** (дату не отдаёт — `published_date` приходит только по
  `include_published_date`/`topic=news`, а запрос не менялся): 70 блоков,
  0 строк «дата публикации»; строка источника в паке —
  `[ИСТОЧНИК 1 | execute_web_search | ok | дата публикации не сообщается источником]`.
* **Exa** (`publishedDate` отдаётся по умолчанию): 47 блоков, 3 строки
  «дата публикации: 2026-11-10»; `SourceRecord` — 47 записей, из них 3 с датой,
  каждая дата привязана к своему URL (vedomosti.ru, lenta.ru, rzn.info);
  агрегатный `EvidenceSource.published_at` пуст (многохитовая выдача);
  строка пака — `[ИСТОЧНИК 1 | execute_web_search | ok | даты публикации — у каждого источника в блоке]`
  и даты в блоках источников.

Тестовые сообщения в Telegram не отправлялись; живого пользовательского поиска в
окне выката не было, поэтому наблюдение получено чтением поискового пути, а не
трафиком чатов.

## Откат

`cd /var/www/admin_bot && git checkout 0fed584598cbf103017a401a117eee236e2be0e5 &&
systemctl restart admin_bot`. Схема и данные не меняются (v47, DDL=0), снапшоты
`predeploy-258181.db` и `predeploy-258182.db` (оба v47) остаются доступны.

## Отклонения и остатки

* В срез вошли 4 файла сверх названных трёх (см. выше) — иначе терялось
  одобренное поведение и падали три теста формата пака.
* Предвыкатный снапшот БД не создавался: DDL=0, данные релиз не пишет,
  схема совместима с существующими снапшотами 2.58.181/2.58.182 (так же
  поступили с 2.58.183).
* Предсуществующая особенность (не этого релиза): многоабзацный `text` Exa
  дробится `_search_blocks` на несколько записей, поэтому «источников» в паке
  больше, чем хитов. На дату не влияет: дата привязывается к записи, где стоит
  URL.
* `deployed_commit` в `plans/features/unified-reply/requirements-map.json`
  остаётся пустым — привязку делает PM/Orchestrator; строка UR-SRC-DATE уже
  VERIFIED на кандидате `7cf8e169`.
