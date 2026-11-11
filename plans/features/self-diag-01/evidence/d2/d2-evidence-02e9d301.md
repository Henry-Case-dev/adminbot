# SELF-DIAG-01 D2 — привязка доказательств принятого кандидата `02e9d301`

Переиздание артефакта `plans/features/self-diag-01/evidence/d2/d2-evidence-f58c458a.md`
(sha256 `56a201fed71941338e5675ac51c1687879a63f85abadf21c73ce1b43c2b6dec2`, 43 331 байт) под
кандидата, принятого на четвёртом проходе независимого ревью. PM в этом проходе продуктовый код не
менял и тесты не перепрогонял: вердикт `Approved` вынесен независимым Reviewer на `02e9d301`, а
здесь зафиксирована только привязка доказательств к этому кандидату и честная история ревью.

**Состояние одной строкой:** D2 принят на `02e9d301` (10 `VERIFIED`, 1 `READY_FOR_LIVE` —
живая проверка после выката, 3 честно открытых `PENDING`), не выкачен, откат `77a63bc5`.

Ниже маркера `<!-- ORIGINAL-BODY-BEGIN -->` тело предыдущего артефакта сохранено **байт-в-байт**
(вместе с его нумерацией строк, SHA и историческими счётчиками), а в нём, в свою очередь, лежит
тело `98bc424e`. Ничего не удалено и не переписано: история — часть доказательства.

## 0.1 Кандидат и линия

| Что | Значение |
|---|---|
| Принятый кандидат | `02e9d301358872a108f8094b0d3742dc0de2e741` |
| Родитель кандидата | `89882aeff6790f79558e0dc5676d5fdf60e3ec4b` |
| База (merge-base с линией производства) | `77a63bc523ce3e5f5537cf11e8d0a3a9737e01f7` — релиз 2.58.184 |
| Ветка | `self-diag/d2-port` (в `master` не влит) |
| Объём от базы | 9 файлов, +4074 / −5 |
| Развёрнуто | **нет**: `deployed_commit` карты пуст, живой приёмки этого кандидата не существует |

Линия коммитов от базы `77a63bc5`:

| # | Коммит | Что изменилось |
|---|---|---|
| 1 | `f58c458a` | портированный кандидат D2 (первый кандидат ревью) |
| 2 | `fef70398` | строка `local_admin` во всех классах + отказ при неполных источниках секретов |
| 3 | `d64adfa7` | доказать strict-чтение BYOK, а не только обработку ошибки |
| 4 | `89882aef` | чекап спрашивает Telegram, санитайзер видит кэш-секреты (родитель принятого) |
| 5 | `02e9d301` | env-секреты в наборе всегда + снимок без кэша не отравляет TTL |

Продуктовые blob'ы принятого кандидата: `services/diagnostic_policy.py` `b6e3b24a`,
`services/output_projection.py` `4fcdd821`, `services/telegram_role_check.py` `093f8e10`,
`services/access.py` `3cd71293`, `web/api/access.py` `b2cf9941`, `handlers/checkup.py` `6ab31598`,
`services/tool_router.py` `6529b512`, `services/chat_keys.py` `748bbd3c`,
`tests/test_diagnostic_policy.py` `04ee22a6`.

## 0.2 Цепочка ревью: четыре прохода

| Проход | Кандидат | Итог | След |
|---|---|---|---|
| 1 | `f58c458a` | `Needs Fixes` — `REV-D2-f58c458a-01`: дефекты `SD1-REV-D2-01` (policy) и `SD1-REV-D2-02` (leak), 11 id-слотов в `FAILED` | исправления `fef70398`, `d64adfa7` |
| 2 | `d64adfa7` | `Needs Fixes` — дефекты политики и утечки закрыты не полностью | исправление `89882aef` |
| 3 | `89882aef` | `Needs Fixes` — остался env-путь секретов и отравление TTL-кэша | исправление `02e9d301` |
| 4 | `02e9d301` | **`Approved`** — `REV-D2-02e9d301-01` | принят к привязке |

Честная граница этой записи: отдельные артефакты проходов 2 и 3 в репозитории не сохранены — их
след только коммиты исправлений и запись очереди ревью в `plans/workflow_state.md`
(2026-11-11 19:12, `d64adfa7` в очереди на независимый вердикт). PM не восстанавливает утраченные
промежуточные артефакты задним числом и не выдаёт за них свои выводы; доказуемы только четыре
прохода как факт, три раунда исправлений и финальный вердикт `Approved` на `02e9d301`.

## 0.3 Что подтвердил последний проход

1. **Env-секреты читаются из `os.environ` независимо от кэша.** `known_secret_values()` вызывает
   `_env_secret_values()` до ветки «конфиг-кэша нет»: для каждой записи `param_catalog.REGISTRY` с
   `secret=True` и заданным `env_name` значение берётся из окружения процесса. Сбой чтения
   окружения помечается в `missing` (`"env"`), снимок становится неполным, и сырой вывод
   блокируется. Тесты: `test_env_only_secret_is_redacted_without_cache` (четыре варианта —
   `tool_result`/`traceback` × кэша нет/промах), `test_env_only_secret_never_leaks_through_dispatch`
   (два варианта через реальный `dispatch`).
2. **TTL-кэш нельзя отравить снимком без кэша.** `_secret_cache` наполняется только при
   `use_cache and cache is not None and snapshot.complete`, поэтому бедный набор без
   `bot_settings` больше не подменяет следующий вызов с живым кэшем. Тест:
   `test_snapshot_without_cache_is_not_reused_by_live_cache`.
3. **Пустое значение секретом не считается.** `_remember()` отсекает пустые и короткие значения
   короче `_MIN_SECRET_LEN`, а также служебные `true/false/none/null`. Тест:
   `test_empty_env_secret_is_not_a_secret`.

Закрытие дефекта первого прохода `SD1-REV-D2-01`: проверка админства включена не только для
`PROTECTED_CLASSES`, но и по матричной строке `local_admin` через `_needs_chat_admin_identity()`,
поэтому `PUBLIC_TECH`/`CHAT_SCOPED` больше не считаются ролью непроверенного участника. Тесты
`test_local_admin_row_is_enforced_for_public_tech_via_dispatch`,
`test_local_admin_row_is_enforced_for_chat_scoped_via_dispatch`,
`test_local_admin_row_still_allows_global_admin`, `test_local_admin_row_rechecks_live_status_before_output`,
`test_local_admin_row_denies_when_admin_check_unavailable`.

Закрытие дефекта первого прохода `SD1-REV-D2-02`: `RAW_OUTPUT_KINDS` включает `tool_result` и
`final`, реестр известных секретов покрывает все секретные поля каталога, включая env-only и
cache-only ключи, ошибка чтения BYOK-ключа даёт `complete=False`, а при недоступности слоя прав
чекап отказывает, а не публикует отчёт. Тесты
`test_incomplete_secret_sources_block_raw_tool_result_and_final`,
`test_tool_result_blocked_when_secret_sources_incomplete`,
`test_publish_blocks_final_when_sources_incomplete`, `test_checkup_report_blocked_when_sources_incomplete`,
`test_checkup_denies_when_policy_layer_unavailable`, `test_byok_read_error_blocks_raw_output`,
`test_unreadable_cache_blocks_raw_output`, `test_credential_registry_covers_every_secret_settings_field`,
`test_every_credential_source_value_is_redacted`, `test_cache_only_secret_key_is_in_consulted_set`,
`test_working_value_from_admin_panel_is_redacted`, `test_cache_only_secret_never_leaks_through_dispatch`,
`test_global_secret_cache_failure_marks_sources_incomplete`,
`test_catalog_failure_marks_sources_incomplete`, `test_settings_field_failure_marks_sources_incomplete`.

## 0.4 Одно неблокирующее замечание

`_remember()` молча отбрасывает не-строковое значение (`if not isinstance(value, str): return`) и не
помечает источник в `missing`, поэтому снимок остаётся `complete=True`. Для `os.environ` это
недостижимо (значение окружения всегда строка), но нестроковое значение из другого источника не
регистрируется в наборе и остаётся прикрытым только pattern-линией. Записано как замечание, а не
дефект: обязательство «значение не выдаётся» этим путём не опровергается, отдельного требования
замечание не создаёт. Если понадобится — отдельная мелкая правка, не повод переоткрывать срез.

## 0.5 Состояние строк после принятия

`VERIFIED` — 10 id-слотов, ранее стоявших в `FAILED`:

| req_id | Строка источника | Чем подтверждено на `02e9d301` |
|---|---|---|
| `SD1-D2-01` | 98 | проекция до модели и до Telegram: `_diagnostic_output` санитизирует любой tool result, `publish()` — финальный отчёт; при неполных источниках `tool_result`/`final` блокируются |
| `SD1-D2-12` | 218 | `project_secret_value()` отдаёт статус без значения; реестр покрывает секретные поля каталога, env-only и cache-only ключи |
| `SD1-D2-14` | 223 | `SECRET_VALUE` — deny до матрицы, включая владельца; неполные источники блокируют сырой вывод; аудит без значений |
| `SD1-D2-15` | 224 | `partially_redacted` и маркер «скрыто:<имя>» на месте значения; `prompt` при неполных источниках — отказ |
| `SD1-D2-18` | 230 | контракт `allow / deny / unverified` с `R_*` считается по подтверждённой роли, включая `local_admin` для публичных и чат-скоупных возможностей |
| `SD1-D2-26` | 273 | общий санитайзер с источниками runtime-секретов и fail-closed для `logs/traceback/prompt/tool_result/final` |
| `SD1-D2-28` | 278 | серверная проекция перед выдачей и перед возвратом результата; обхода при сбое слоя прав больше нет |
| `SD1-AMX-02` | 198 | матрица различает участника, чат-админа и владельца; админство — только `getChatMember` по числовым идентификаторам |
| `SD1-AMX-05` | 212 | абсолютный запрет держится на всех путях, включая неполные и недоступные источники секретов |
| `SD1-AC-15` | 444 | проверка до чтения и перед отправкой; недоступность слоя прав — отказ, а не обход |

`READY_FOR_LIVE` — 1 id-слот:

| req_id | Строка источника | Почему не `VERIFIED` |
|---|---|---|
| `SD1-AC-14` | 443 | политическая часть доказана на кандидате, но живая проверка «ноль раскрытий» на всех маршрутах (error/caching/source/tool/replay, промпт, лог, конфиг, исходники) возможна только после выката; условие — `postdeploy_condition` строки |

`PENDING` — 3 честно открытых строки, ни одна не является дефектом D2:

| req_id | Почему открыта |
|---|---|
| `SD1-AMX-09` | вход `inspect_runtime` появится в D3, отрисованная админская поверхность — в D6; карту `TOOL_CAPABILITIES` нужно подтвердить на реальном вызове после их появления |
| `SD1-D2-23` | обязательность флага sensitivity при регистрации провайдера не обеспечена: `ParamSpec.secret` по-прежнему по умолчанию `False`; вторая часть причины (неполный реестр runtime-секретов) закрыта `02e9d301` и из причины убрана |
| `SD1-D2-24` | нужны evidence bundle D3 (`SD1-EVD-04`) и типизированный settings adapter с `configured/effective/last_success/last_error_code/key_fingerprint` — в кандидате этих компонентов нет |

## 0.6 Учёт среза D2

| Слой учёта | записей | VERIFIED | READY_FOR_LIVE | PENDING | FAILED |
|---|---|---|---|---|---|
| весь срез D2 — записи | 44 | 35 | 6 | 3 | 0 |
| весь срез D2 — уникальные `req_id` | 42 | 33 | 6 | 3 | 0 |

Дельта относительно состояния `Needs Fixes` (11 `FAILED`): 10 слотов → `VERIFIED`, 1 слот
(`SD1-AC-14`) → `READY_FOR_LIVE`, `PENDING` не менялись (3 → 3). 6 id-слотов `READY_FOR_LIVE` — это
5 живых обязательств: `SD1-D2-03` и `SD1-D2-03b` описывают одно требование двумя строками
источника. Счётчики зафиксированы в `requirements-map.json` → `slice_accounting`.

## 0.7 Предыдущие артефакты сохранены

| Артефакт | Кандидат | sha256 | Состояние |
|---|---|---|---|
| `evidence/d2/d2-evidence-98bc424e.md` | `98bc424e` | `f9f6601c801fccb729b0ada1cb9a6c2b893d36d223cc7f41a6b4f91f0cbc625c` | superseded, файл не изменён |
| `evidence/d2/d2-evidence-f58c458a.md` | `f58c458a` | `56a201fed71941338e5675ac51c1687879a63f85abadf21c73ce1b43c2b6dec2` | superseded этим артефактом, файл не изменён, его тело входит сюда байт-в-байт |

## 0.8 Деплой

- `deployed_commit` карты остаётся `""` — **выката не было**, ни одно живое поведение D2 этим
  артефактом не подтверждено.
- Откат: `77a63bc523ce3e5f5537cf11e8d0a3a9737e01f7` (релиз 2.58.184) — кандидат ничего не
  заменял и в производстве не участвовал.
- Релиз D2 поставлен в очередь **после текущего** релиза; последний подтверждённый выкат по
  `plans/workflow_state.md` — 2.58.186 @ `d96b24ab`, текущая работа DevOps — 2.58.187. Состав и
  номер следующего релиза определяет DevOps, а не этот артефакт.

## 0.9 Гейты (дословно)

План-гейт:

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check --map plans/features/self-diag-01/requirements-map.json --graph plans/features/self-diag-01/slice-graph.json --stage plan --repo .
```

```
stage=plan inventory=183 manual=53 scoped=0 errors=0
```

Ревью-гейт среза D2:

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check --map plans/features/self-diag-01/requirements-map.json --graph plans/features/self-diag-01/slice-graph.json --stage review --slice D2 --candidate 02e9d301358872a108f8094b0d3742dc0de2e741 --repo .
```

```
FAIL: SD1-D2-23: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SD1-D2-24: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SD1-AMX-09: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=183 manual=53 scoped=44 errors=3
```

План-гейт чистый (`errors=0`). Ревью-гейт красный ровно на трёх открытых строках — это не дефект
привязки и не регресс, а честно незакрытые обязательства с чужим исполнителем:

- `SD1-D2-23` — обязательность флага sensitivity при регистрации провайдера (`ParamSpec.secret` по
  умолчанию `False`); ждёт правки каталога параметров, а не D2.
- `SD1-D2-24` — evidence bundle D3 (`SD1-EVD-04`) и типизированный settings adapter
  (`configured/effective/last_success/last_error_code/key_fingerprint`); этих компонентов в
  кандидате нет.
- `SD1-AMX-09` — входы `inspect_runtime` (D3) и отрисованная админская поверхность (D6).

Все десять перепривязанных строк и `SD1-AC-14` гейт проходят: обязательный статус соблюдён
(`READY_FOR_LIVE` разрешён на ревью только для `live_required` + `live_when=postdeploy`), а каждая
запись `evidence` привязана к кандидату `02e9d301` и указывает на существующий файл с совпадающим
sha256.

## 0.10 Что остаётся

1. Выкат релиза с кандидатом `02e9d301` штатным путём DevOps и снятие живой приёмки `SD1-AC-14`
   (`postdeploy_condition`, откат `77a63bc5`).
2. Три открытых `PENDING` — по своим условиям (D3/D6 и обязательный флаг sensitivity), не блокируют
   выкат этого среза.
3. Единственное неблокирующее замечание — §0.4; отдельного требования не создаёт.


<!-- ORIGINAL-BODY-BEGIN -->
# SELF-DIAG-01 D2 — привязка доказательств портированного кандидата `f58c458a`

Переиздание артефакта `plans/features/self-diag-01/evidence/d2/d2-evidence-98bc424e.md`
(sha256 `f9f6601c801fccb729b0ada1cb9a6c2b893d36d223cc7f41a6b4f91f0cbc625c`, 29 258 байт) для
кандидата, перенесённого на линию производства 2.58.184. Продуктовый код в этом проходе не
менялся, тесты PM не перепрогонял: поведенческий вердикт остаётся за независимым Reviewer и снят
на `98bc424e`, чьё продуктовое содержимое побайтово совпадает с портированным (см. §0.1).

Ниже маркера `<!-- ORIGINAL-BODY-BEGIN -->` тело предыдущего артефакта сохранено **байт-в-байт** —
вместе с его нумерацией строк, SHA и историческими счётчиками. Всё, что относится к актуальному
кандидату, — в §0.1–§0.10 выше маркера.

## 0.1 Кандидат и доказательство переноса

| Что | Значение |
|---|---|
| Портированный кандидат | `f58c458a2efdb1613fe519143c9ad7517c37ecc8` |
| Родитель (линия производства) | `77a63bc523ce3e5f5537cf11e8d0a3a9737e01f7` — релиз 2.58.184 |
| Источник переноса (cherry-pick) | `98bc424ef719083b9392a84918bab0af3b87c587`, родитель `3b1ba3b2c0b3cb69ecdc5fcc0c5cd54ddfc53515` |
| Ветка | `self-diag/d2-port` (в `master` не влит) |
| Объём | 8 файлов, +2946 / −3 — совпадает с исходным кандидатом |
| Развёрнуто | **нет**: `deployed_commit` карты по-прежнему `""`, живой приёмки этого кандидата не существует |

Побайтовая идентичность продуктовых файлов (blob в Git):

| Файл | blob в `98bc424e` | blob в `f58c458a` |
|---|---|---|
| `services/diagnostic_policy.py` | `411b0b68` | `411b0b68` |
| `services/output_projection.py` | `f803fa06` | `f803fa06` |
| `services/telegram_role_check.py` | `093f8e10` | `093f8e10` |
| `services/access.py` | `3cd71293` | `3cd71293` |
| `web/api/access.py` | `b2cf9941` | `b2cf9941` |
| `handlers/checkup.py` | `5a84c67b` | `5a84c67b` |
| `tests/test_diagnostic_policy.py` | `ff5d76ba` | `ff5d76ba` |
| `services/tool_router.py` | `956367d3` | `2ce89ac1` |

Семь файлов из восьми совпадают побайтово. Различие только в `services/tool_router.py`, и это
изменения самого производства: содержательная часть диффа
`98bc424e:services/tool_router.py → f58c458a:services/tool_router.py` построчно совпадает с диффом
`3b1ba3b2:services/tool_router.py → 77a63bc5:services/tool_router.py` того же файла (339 строк
изменённого текста, различаются только заголовки `@@` из-за сдвига номеров строк; изменений нет).
Блок D2 в этом файле не тронут: те же 92 строки, тот же текст, другая позиция.

## 0.2 Номера строк: что устарело, что осталось верным

| Ссылка в `services/tool_router.py` | на `98bc424e` | на `f58c458a` |
|---|---|---|
| блок D2 целиком (комментарий `SELF-DIAG-01 D2` → `return sanitized.text`) | 1397–1488 | **1435–1526** |
| вызов гейта в `ToolRouter.dispatch` (`_diagnostic_guard` / `_diagnostic_output`) | 1400 / 1414 | 1438 / 1452 |
| `_diagnostic_guard` | 1435 | 1473 |
| `_diagnostic_output` | 1451 | 1489 |

- Действующая нумерация для всех будущих доказательств — **1435–1526** на `f58c458a`; любые
  ссылки на 1397–1488 относятся к `98bc424e` и на портированном кандидате устарели (сдвиг +38).
- Отдельно проверено: ссылки `tool_router.py:1394` в теле артефакта **нет** (поиск по файлу).
  Три абсолютные ссылки, которые в теле есть, — `telegram_role_check.py:132-146`,
  `output_projection.py:53-64`, `diagnostic_policy.py:260-267` — указывают на файлы, чьи blob'ы в
  обоих кандидатах совпадают (см. §0.1), поэтому остаются верными и пересчёту не подлежат.

## 0.3 Что перепривязано в карте требований

- `candidate_commit` карты: `98bc424e…` → `f58c458a2efdb1613fe519143c9ad7517c37ecc8`
  (исходный кандидат сохранён полем `candidate_origin_commit`).
- 41 запись `evidence` (28 строк `items` + 13 строк `additional_requirements`), ранее привязанная
  к `98bc424e` и к файлу `d2-evidence-98bc424e.md`, перепривязана к `f58c458a` и к этому файлу:
  у каждой записи обновлены `candidate_commit`, `artifact_path`, `artifact_sha256` и `ref`.
- `deployed_commit` остаётся `""`: выката не было, ни одно живое поведение этим артефактом не
  подтверждено.

## 0.4 Учёт строк среза D2: откуда взялось расхождение «26/2/2» против «33/5/3»

Причина — не арифметика, а два разных среза одной карты. Срез D2 в карте собран из двух массивов:
`items` (извлечённая инвентаризация исходного файла) и `additional_requirements` (ручные строки ТЗ
с нормативной ссылкой на строку источника). Фильтр только по `items` даёт «26 / 2 / 2», весь срез
даёт «33 / 5 / 3» по уникальным `req_id`:

| Слой учёта | записей | VERIFIED | READY_FOR_LIVE | PENDING |
|---|---|---|---|---|
| только `items` (`slice == "D2"`) | 30 | 26 | 2 | 2 |
| только `additional_requirements` (`slice == "D2"`) | 14 | 9 | 4 | 1 |
| **весь срез D2 — записи** | **44** | **35** | **6** | **3** |
| весь срез D2 — уникальные `req_id` до разделения `SD1-D2-03` | 41 | 33 | 5 | 3 |
| весь срез D2 — уникальные `req_id` после разделения (`SD1-D2-03` + `SD1-D2-03b`) | 42 | 33 | 6 | 3 |

Как сходятся числа: `26 + 9 − 2 = 33` VERIFIED — две пары записей (`SD1-GRAL-05`, `SD1-AMX-07`)
хранят один и тот же `source_line` одновременно в `items` и в `additional_requirements`, `req_id`
у них один и статус согласован; `2 + 4 − 1 = 5` READY_FOR_LIVE — `SD1-D2-03` был записан дважды;
`2 + 1 = 3` PENDING. Обратная сверка: набор 33 VERIFIED-`req_id` совпадает с перечнем §5 тела
один в один (расхождений нет).

Что действительно было сломано и исправлено:

1. **`SD1-D2-03` занимал два слота под одним `req_id`** (`source_line` 198 и 527) — нарушение
   правила карты «единственный владелец строки = `req_id`». Обе строки сохранены, вторая получила
   `SD1-D2-03b` (см. §0.5).
2. **Ни в карте, ни в графе не было счётчика среза**, поэтому «26 / 2 / 2» и «33 / 5 / 3» читались
   как взаимоисключающие. Счётчик зафиксирован в карте (поле `slice_accounting`) и в §0.4.
3. **§8 тела** («scoped=47 … 44 уникальных req_id») — историческое состояние до перераспределения
   владельцем 2026-11-10; текущее состояние среза — 44 записи / 41 `req_id` до правки и 42 после.
   **§10 тела** (41 строка, 33 / 5 / 3) верен на момент записи и остаётся верным по существу;
   после разделения `SD1-D2-03b` уникальных `req_id` в срезе 42 при тех же 33 VERIFIED.

Вывод: числа в теле артефакта верны, ошибочным был способ подсчёта «только по `items`»; кроме
того, карта не давала однозначного счётчика и содержала дубль `req_id`.

## 0.5 `SD1-D2-03` и `SD1-D2-03b` — одно требование из двух строк источника

| Строка | `source_line` | Что это | Приёмка |
|---|---|---|---|
| `SD1-D2-03` | 198 | нормативная строка: `chat_admin` подтверждается online `getChatMember` по числовым `from_user.id` и `chat.id` | общая |
| `SD1-D2-03b` | 527 | строка §«Источники»: ссылка на Telegram Bot API и требование, что бот должен быть администратором группы | общая |

- Приёмка, статус (`READY_FOR_LIVE`, `live_when=postdeploy`) и живое доказательство у обеих строк
  одни и те же; живой артефакт один — `plans/features/self-diag-01/evidence/d2/sd1_d2_03.json`.
- Строки не слиты, потому что это два разных `source_line`; `req_id` разные, чтобы правило
  «единственный владелец строки = `req_id`» не нарушалось. В `slice-graph.json` обе внесены в
  `requirements` D2 и в `external_dependencies[EXT-TG-ADMIN].affects`.

## 0.6 DDL, миграции, флаги: отсутствуют

Проверено по всему диффу переноса (2946 добавленных строк, 8 файлов): ноль `CREATE TABLE` /
`ALTER TABLE` / `CREATE INDEX`, ноль упоминаний миграций, ноль `FEATURE_*` / `feature_flag`, ноль
`os.getenv` / `os.environ`. Поведение среза — **безусловный слой политики**: `TOOL_CAPABILITIES`
из `services/diagnostic_policy.py` гейтит три инструмента (`get_bot_health`, `read_source_code`,
`inspect_runtime`; из них зарегистрированы сегодня первые два, `inspect_runtime` регистрируется в
D3), решение принимается в `ToolRouter.dispatch` до выполнения и перепроверяется перед возвратом.

Поэтому правило проекта «готовая функция включается заводским значением флага» к D2 не
применяется: включать нечего, выключенного состояния у слоя политики нет. Существующий
env kill-switch у `read_source_code` (`source_read_enabled()`) был до D2 и этим срезом не менялся.

## 0.7 Базовая линия будущих доказательств

- Базовая линия для любых будущих доказательств и сравнений — родитель порта
  `77a63bc523ce3e5f5537cf11e8d0a3a9737e01f7` (релиз 2.58.184), а **не** `adfd0d0`.
  `adfd0d0c` — коммит другого эпика (MOD-ACL-UX-01 M1), к D2 отношения не имеет.
- В карте, графе и `plan.md` этого эпика ссылок на `adfd0d0` нет (проверено поиском); если такая
  ссылка встречалась в переписке о переносе, она ошибочна.

## 0.8 Предыдущий артефакт: сохранён как superseded

| Что | Значение |
|---|---|
| Путь | `plans/features/self-diag-01/evidence/d2/d2-evidence-98bc424e.md` |
| sha256 | `f9f6601c801fccb729b0ada1cb9a6c2b893d36d223cc7f41a6b4f91f0cbc625c` |
| Состояние | **superseded**, не удалён и не изменён; его тело входит в этот файл байт-в-байт |

## 0.9 Результат плана-гейта (дословно)

```
stage=plan inventory=183 manual=53 scoped=0 errors=0
```

## 0.10 Что остаётся до выката

До выката остаётся один инженерный шаг — свежий review-gate на `f58c458a` по срезу D2 (поведенческий
вердикт Reviewer уже получен на побайтово том же продуктовом коде), после чего срез уходит в релиз
штатным порядком; пять живых обязательств (шесть записей: `SD1-D2-03` и `SD1-D2-03b` — одно)
закрываются живым подтверждением уже после выката, а три `PENDING` (`SD1-AMX-09`, `SD1-D2-23`,
`SD1-D2-24`) ждут D3/D6 и решения по обязательности флага sensitivity при регистрации провайдера —
это не дефекты D2 и не причина держать выкат.

<!-- ORIGINAL-BODY-BEGIN -->
# SELF-DIAG-01 D2 — привязка доказательств кандидата `98bc424e`

Артефакт составлен PM после независимого ревью кандидата `98bc424ef719083b9392a84918bab0af3b87c587`
и связывает срез **D2** карты `plans/features/self-diag-01/requirements-map.json` с фактически
проверенным кодом. Продуктовый код в этом проходе не менялся, тесты PM не перепрогонял:
поведенческий вердикт принадлежит независимому Reviewer, здесь он зафиксирован построчно —
с именами тестов из дерева кандидата, текстом утверждений и честной границей непроверенного.

Вердикт Reviewer по кандидату: **Needs Fixes, но дефекта безопасности не найдено.** Все
поведенческие требования прошли; три блокера процессные (карта фичи отсутствует в checkout
кандидата, граница визуальной приёмки и граница живой приёмки Telegram).

## 1. Кандидат

| Что | Значение |
|---|---|
| Кандидат | `98bc424ef719083b9392a84918bab0af3b87c587` |
| Родитель | `3b1ba3b2c0b3cb69ecdc5fcc0c5cd54ddfc53515` |
| Сообщение | `feat(self-diag): SELF-DIAG-01 D2 — политика доступа к диагностике` |
| Ветка | `integ/unify-release` (`git merge-base --is-ancestor 98bc424e master` → 1, в `master` не влит) |
| Объём | 8 файлов, +2946 / −3 |
| Продуктовые файлы | `services/diagnostic_policy.py` (+939), `services/output_projection.py` (+294), `services/telegram_role_check.py` (+161), `services/access.py` (+117), `web/api/access.py` (+267), `services/tool_router.py` (+86/−3), `handlers/checkup.py` (+73) |
| Тесты кандидата | `tests/test_diagnostic_policy.py` — 40 функций `def test_` (35 async + 5 sync), включая FastAPI-путь админского API |
| Развёрнуто | **нет.** `deployed_commit` карты по-прежнему `""`; живой приёмки этого кандидата не существует |

Что именно делает кандидат (по коду, не по сообщению коммита): один слой решений
`(actor, chat_scope, data_class, action, destination) → allow|deny|unverified` с машинным
`reason_code`; жёсткие правила (`SECRET_VALUE`, промпт участнику, чужая область чата,
неудостоверяемая личность) стоят **до** матрицы; чат-админ подтверждается только онлайн
`getChatMember` по числовым `chat_id`/`from_user.id`; отзыв прав перепроверяется перед возвратом
результата инструмента и перед публикацией; секреты вычищаются структурно (по фактическим
значениям из типизированных источников, паттерны — вторая линия); аудит хранит только
метаданные. Второго ACL нет: роль владельца — `services.roles.access_for`, матрица — существующие
`param_permissions` + `chat_params.perm_overrides`.

## 2. Структурный блокер №1: карта фичи отсутствует в checkout кандидата

Проверено фактически:

```
git ls-tree 98bc424e plans/features/                    → 59 записей, среди них mod-acl-ux-01 есть
git ls-tree 98bc424e plans/features/self-diag-01/       → пусто
git ls-tree 98bc424e plans/owner_inputs/ | grep self-diag → пусто
```

Причина не в продукте: `plans/features/self-diag-01/` и `plans/owner_inputs/2026-11-09-self-diag-01.md`
созданы уже после точки ветвления `integ/unify-release`. Это та же структурная ситуация, что была
у MOD-ACL M2.

**Решение (то же, что зафиксировано для MOD-ACL):** review-gate **всегда** запускается из
основного checkout против SHA кандидата — `--repo . --candidate <sha>`. Карта в релизную ветку не
переносится: одна карта — один живой леджер, вторая копия немедленно разошлась бы с `master`.
Это процессное ограничение, а не дефект D2; строка «карта отсутствует в checkout» дефектом не
считается.

## 3. Решение по границе №2: визуальная приёмка принадлежит D6

Ревьюер проверял демо-поверхность потому, что политика упоминает админ-UI. Зафиксировано явно:

- **D2 — слой политики.** Строки D2, которые описывают только решение/класс/проекцию/аудит,
  закрываются политическими тестами и рендера не требуют.
- **D6 — отрисованная поверхность.** Строки, для закрытия которых нужен экран, перенесены
  владельцем в D6: `SD1-AMX-01` (подраздел «Самодиагностика» в разделе «Доступы») и
  `SD1-D2-32` (матрица и аудит в админке). Условие приёмки записано в карте и в
  `slice-graph.json`: **отрисованная поверхность Access/Self-Diagnosis, Playwright плюс
  независимый браузер, desktop и mobile**.
- Повторно открывать эти строки как дефект D2 нельзя: политическая часть (9 категорий,
  view/run/edit, отсутствие второго ACL, объяснение наследования, аудит без содержимого) уже
  доказана строками `SD1-D2-07`, `SD1-AC-16`, `SD1-AMX-02`, `SD1-AMX-07`.
- `SD1-D2-08` и `SD1-D2-11` перенесены владельцем в D5: их приёмка требует фактической выдачи
  промпта (дублируют `SD1-AMX-04` и `SD1-D5-08`), политическая часть уже доказана.

## 4. Решение по границе №3: живая приёмка Telegram — обязательство после выката

До деплоя реальную проверку выполнить нельзя, поэтому пять строк D2 переведены в
`READY_FOR_LIVE` с `live_when=postdeploy`, точным условием в `postdeploy_condition` и ссылкой на
откат в `rollback_ref`:

| Строка | Условие после выката |
|---|---|
| `SD1-D2-03` | настроенный числовой Telegram ID получает `chat_admin` по факту `getChatMember` (administrator и creator), участник — нет; отсутствие прав бота даёт `auth_unverified` без protected readback |
| `SD1-AMX-08` | реальная смена статуса администратора во время идущего чекапа — публикации нет, в аудите `revocation_detected` на переходе allow→deny; отдельно «бот не в чате» и отзыв через настройки без рестарта |
| `SD1-AC-10` | в реальном публичном чате участник задаёт произвольный технический вопрос без «чекап» и получает содержательный ответ без credential values и чужих chat contents |
| `SD1-AC-11` | в реальном чате попытки получить действующий промпт прямым запросом, через tool result, cache/metadata и prompt injection — все denied без фрагментов |
| `SD1-AC-14` | перебор маршрутов error/caching/source/tool/replay и запросов к промпту, логу, конфигу, исходникам — ноль раскрытий credential values, включая владельца и админа |

Откат для всех пяти один: возврат на предыдущий неизменяемый релиз **2.58.174 @ `ac943f40`**
(release branch, чистый SHA) без переноса состояния. Пока живое доказательство не снято, эти
строки не могут стать `VERIFIED`, а срез D2 — полным `VERIFIED`.

## 5. Леджер: 33 строки доказаны этим кандидатом

Для каждой строки доказательство — конкретное утверждение теста на дереве кандидата
(`tests/test_diagnostic_policy.py`, если не указано иное) либо читаемый участок кода.

### Роли и идентичность
- `SD1-D2-02` — `resolve_actor()` отдаёт `ROLE_MEMBER` любому удостоверяемому участнику, включая
  личный диалог (`chat_id>0 → STATUS_MEMBER`); публичные классы разрешены (`test_member_reads_public_tech_but_not_prompts`,
  `test_dm_scope_is_member_not_admin`).
- `SD1-D2-04` — владелец только из существующего контура `roles.access_for(...).is_global_admin`
  (`test_project_owner_from_existing_owner_contour`), не «первый админ Telegram».
- `SD1-D2-05` — без `from_user.id` право не возникает: `R_DENY_NO_IDENTITY`/`R_DENY_PROMPT_MEMBER`
  (`test_anonymous_sender_gets_no_prompt_rights`); `sender_chat` в `resolve_actor` не участвует.
- `SD1-D2-06` — проверка в момент решения; `bot=None` → `bot_unavailable`, исключение API →
  `telegram_api_error`, оба `unverified` без raise (`telegram_role_check.py:132-146`);
  `test_auth_unverified_denies_protected_only` (prompts → unverified, bot_server_state → allow).
- `SD1-AMX-02` — три роли матрицы + сопоставление актора со строкой существующей матрицы;
  `bot.calls == [(GROUP_A, ADMIN_ID)]` в `test_chat_admin_verified_by_telegram_api`,
  `test_nickname_and_claims_do_not_grant_admin`, `test_matrix_override_cannot_open_prompts_to_member`.

### Классы данных и матрица
- `SD1-D2-07` — пять классов и правило класса в `default_diag_matrix()`; `test_default_matrix_role_by_class`,
  `test_other_chat_data_rule`, `test_secret_value_class_never_allowed`.
- `SD1-D2-18` — контракт `(actor, chat_scope, resource_chat_id, data_class, action)` с машинными
  `reason_code`; матрица — существующий слой `param_permissions` + `chat_params.perm_overrides`
  (`test_chat_override_beats_global_and_survives_restart`, `test_matrix_snapshot_has_inheritance_and_legend`).
- `SD1-AC-16` — структурные метаданные класса, ресурсный ACL, типизированный каталог как источник
  истины о секретах, общий `sanitize()`; паттерны объявлены второй линией (`output_projection.py:53-64`).

### Жёсткие правила (до матрицы)
- `SD1-AMX-05` — `SECRET_VALUE` = deny участнику и владельцу, `configurable: false` в снапшоте
  (`test_secret_value_class_never_allowed`, `test_matrix_snapshot_has_inheritance_and_legend`).
- `SD1-D2-12` — значение не возвращается ни под настройкой, ни под исходником/логом/конфигом:
  `project_secret_value()` даёт только `name/configured/last4/status`, `sanitize()` применяется и к
  немаркированным инструментам (`test_secret_projection_never_returns_value`,
  `test_non_diagnostic_tool_result_is_sanitized`).
- `SD1-D2-13` — `PROMPT_CONTENT` отдельный класс, а не `SECRET_VALUE`
  (`sensitivity_of_pg_key('prompts.checkup_system_prompt') == PROMPT_CONTENT`).
- `SD1-D2-14` — значение недоступно при любой роли; владелец управляет ключом, но не получает текст
  (`test_secret_value_class_never_allowed`, `test_audit_records_decisions_without_secrets`).
- `SD1-D2-15` — маска + `partially_redacted` + маркер «скрыто:<имя>»; fail-closed для `prompt` при
  недоступных источниках (`test_sanitize_removes_values_and_fails_closed_for_raw_logs`).
- `SD1-D2-09` — участнику короткий отказ без фрагментов и без перечня инструкций, публичная техника
  сохраняется (`test_member_reads_public_tech_but_not_prompts`, `test_explain_is_plain_language_and_secret_aware`).
- `SD1-D2-10` — админ A в чате B получает deny, проверка идёт по `(GROUP_B, ADMIN_ID)`
  (`test_admin_of_chat_a_gets_no_chat_b_prompt`); чужие данные — отдельное hard_rule
  (`test_other_chat_data_rule`).

### Проверка до чтения, до результата и перед отправкой
- `SD1-AC-15` — отказ до чтения и до отправки (`test_checkup_entry_respects_policy_without_reading_logs`:
  `fetcher.fetch` и `service.checkup` не вызывались; `test_tool_call_is_denied_by_policy`).
- `SD1-D2-19` — три точки + `fresh_telegram=True` игнорирует TTL-кэш
  (`test_admin_status_changed_mid_session`, `test_revocation_blocks_publication_of_running_check`,
  `test_policy_change_revokes_running_chat_admin_check`, `test_checkup_entry_publishes_after_recheck`).
- `SD1-D2-20` — решение принимает сервер, подмена `user_id`/`role` в args не поднимает права
  (`test_paraphrased_request_and_args_do_not_elevate`).
- `SD1-D2-22` — отказ не гасит остальную диагностику (`test_auth_unverified_denies_protected_only`).
- `SD1-D2-17` — principal только из Telegram-контекста (`ToolContext.chat_id/user_id`,
  `message.from_user.id`), аргументы модели игнорируются.
- `SD1-D2-21` — у разрешения свой контекст (`DiagnosticGate`), содержимое не кэшируется и не
  логируется, переиспользования между акторами нет (`test_concurrent_admin_and_member_do_not_share_data`).
- `SD1-D2-34` — перед доставкой права перепроверяются заново (`publish → recheck_gate`).
- `SD1-D2-35` — одинаковый текст запроса не даёт общего результата (`[True, False]` в
  `test_concurrent_admin_and_member_do_not_share_data`).

### Секреты в выводе
- `SD1-D2-01` — фильтрация до модели и до Telegram (`ToolRouter._diagnostic_output`,
  `publish → sanitize(kind='final')`), `prompt_digest()` без текста (`test_prompt_digest_has_no_text`).
- `SD1-D2-26` — логи/traceback/любой результат проходят общий санитайзер, fail-closed для
  `logs/traceback/prompt` при недоступных источниках.
- `SD1-D2-27` — паттерны только вторая линия, не единственная защита и не маршрутизация намерения.
- `SD1-D2-28` — серверная проекция вывода, а не просьба в промпте
  (`test_tool_result_never_leaks_secret`, `test_checkup_report_redacts_secrets`).
- `SD1-D2-30` — имена настроек, факт наличия ключа и причина отказа остаются видимыми.

### Аудит
- `SD1-AMX-07` — `decision/denial/gate_open/publication/policy_change/role_check` с actor/chat/role/
  effect/reason/source, `changed_by`/`before`/`after` только в белом списке полей
  (`diagnostic_policy.py:260-267`), секрет и текст промпта отсутствуют и в снапшоте, и в `caplog`
  (`test_audit_records_decisions_without_secrets`), раскрытие фиксируется без текста
  (`test_prompt_disclosure_audit_without_text`).

### Все входы и прозрачность
- `SD1-GRAL-03` — нет скрытия по признаку «внутренности сервера», запрет только по классу/границе/секрету.
- `SD1-GRAL-05` — общей маски на исходный код нет: `source_code` открыт участнику
  (`test_member_reads_public_tech_but_not_prompts`).
- `SD1-SEM-05` — структурная карта `TOOL_CAPABILITIES` вместо regex по описанию/тексту; проверка
  после выбора инструмента в `ToolRouter.dispatch` (`test_indirect_tool_bypass_is_blocked`).
- `SD1-D2-31` — техническое обсуждение не блокируется, ограничен именно запрос промпта.

## 6. Что осталось и при каком условии

### 6.1 Шесть строк D2 остаются PENDING (привязкой этого кандидата не закрываются)

| Строка | Что не выполнено и точное условие |
|---|---|
| `SD1-AMX-09` | Доказано: гейт стоит в единой точке `ToolRouter.dispatch` и в обработчике чекапа, API матрицы требует global_admin (`test_api_requires_global_admin`), кнопки не единственная защита. Не закрыто: входа `inspect_runtime` ещё нет (D3) и отрисованной админской поверхности нет (D6); после их появления та же карта должна быть подтверждена на реальном вызове |
| `SD1-D2-16` | Классификация «заводской промпт, уже опубликованный в публичном GitHub» не реализована: кандидат защищает все промпты как `PROMPT_CONTENT`. Это не утечка (защита строже), но нормативная прозрачность не выполнена; владельца у пункта сейчас нет |
| `SD1-D2-23` | `sensitivity_of_pg_key` реализован по `param_catalog`, но «для нового провайдера sensitivity обязательна при регистрации» не обеспечено: `ParamSpec.secret` по умолчанию `False`, новый провайдер без флага молча становится `NON_SECRET_CONFIG` |
| `SD1-D2-24` | `DiagnosticEvidenceBundle` появится в D3 (`SD1-EVD-04`); типизированный settings adapter с `configured/effective/last_success/last_error_code/key_fingerprint` не добавлен |
| `SD1-D2-25` | Чтение `.env`/credential-конфигов инструментом не ограничено: source reader этим кандидатом не менялся (D4), typed settings adapter не добавлен; у пункта нет владельца-слайса |
| `SD1-D2-29` | Доказано только для tool result, финальной доставки, аудита и логов слоя. Не покрыто: observability traces, debug requests, retries, source references (D4), HTML/Markdown preview (D6); у этих поверхностей нет владельца-строки |

`SD1-AMX-09`, `SD1-D2-23`, `SD1-D2-25`, `SD1-D2-29` — не «остатки ревью», а **отсутствующие
владельцы** подпунктов: чтобы закрыть срез, нужно решить, какой слайс их исполняет, и только потом
ставить статус.

### 6.2 Пять строк `READY_FOR_LIVE` (см. §4) — только после выката.

### 6.3 Четыре строки перенесены владельцем (см. §3): `SD1-AMX-01`, `SD1-D2-32` → D6; `SD1-D2-08`, `SD1-D2-11` → D5.

## 7. Предсуществующие падения набора (не регресс D2)

Ревьюер зафиксировал три падения, которые воспроизводятся на родителе `3b1ba3b2` и не связаны с
этим кандидатом: `test_every_editable_prompt_has_reachable_surface`,
`test_forbidden_paths_out_of_diff`, `test_grep_audit_counts_are_stable`. Записано один раз в
`plans/backlog.md` как пункт обслуживания; D2 они не блокируют и в карту требований D2 не входят.

## 8. Результат gate (main checkout, `--repo .`)

План-гейт после привязки:

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/self-diag-01/requirements-map.json --stage plan --repo .
→ stage=plan inventory=183 manual=53 scoped=0 errors=0
```

Ревью-гейт, срез D2, кандидат `98bc424e`:

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/self-diag-01/requirements-map.json \
  --stage review --slice D2 --candidate 98bc424e… --repo .
→ stage=review inventory=183 manual=53 scoped=47 errors=6
  все шесть: mandatory not ['VERIFIED'] (got PENDING)
  SD1-AMX-09, SD1-D2-16, SD1-D2-23, SD1-D2-24, SD1-D2-25, SD1-D2-29
```

`scoped=47` — это строки среза (44 уникальных `req_id`: у `SD1-D2-03`, `SD1-AMX-07`, `SD1-GRAL-05`
по две исходные строки с одинаковой приёмкой). Ни одной ошибки привязки доказательств:
`artifact_path`/`artifact_sha256`, Git-объект кандидата, типы живых доказательств и граф слайсов
проходят проверку. Оставшиеся шесть ошибок — честный остаток работ из §6.1, а не дефект привязки.

## 9. Честная граница

- PM не перепрогонял тесты: имена тестов и утверждения взяты из дерева `98bc424e`, поведенческий
  вердикт — независимого Reviewer.
- Кандидат **не развёрнут**: ни одно живое поведение этим артефактом не подтверждено.
- Границы, зафиксированные в карте полем `boundary` у отдельных строк, означают: доказана часть
  D2, а названная часть принадлежит другому слайсу и там отслеживается (`SD1-EVD-04` для
  evidence-буфера, `SD1-EVD-13` для бюджета вывода, D5 для текста предупреждения и выдачи промпта,
  D3/D7 для попадания результата в память и историю LLM).
- Срез D2 **не является** полным `VERIFIED`: 33 строки доказаны, 5 ждут выката, 6 требуют
  исполнения или назначения владельца.

## 10. Решение владельца 2026-11-10: три подпункта получили исполнителя

§6.1 сохраняется как история состояния на момент привязки (`98bc424e`, 6 PENDING). После того как PM
честно зафиксировал, что у трёх подпунктов нет владельца-слайса, владелец назначил их сам — **без нового
гейта проверки, только распределение ответственности**:

| Строка | Владелец | Почему одной строкой |
|---|---|---|
| `SD1-D2-25` — чтение `.env`/credential-конфигов инструментом не ограничено | **D4** | ограничение принадлежит тому слайсу, который вводит сам механизм чтения (source reader, deploy identity, SHA, история коммитов) |
| `SD1-D2-29a` — observability traces, debug requests, retries, source references | **D4** | эти поверхности порождает та же runtime-introspection поверхность, что и D4 |
| `SD1-D2-29b` — HTML/Markdown preview | **D6** | предпросмотр — отрисованная поверхность, её приёмка идёт с Playwright и независимым браузером |
| `SD1-D2-16` — заводской промпт из публичного GitHub классифицируется как публичный | **D5** | раскрытие и классификацию промптов определяет prompt readback |

Форма записи: `SD1-D2-29` остаётся одной строкой с держателем **D4** и двумя подпунктами
(`sub_obligations`: `SD1-D2-29a` → D4, `SD1-D2-29b` → D6); строка закрывается после обеих частей, ни одна
не теряется. Приёмка, `source_line`/`source_sha256` и история строк не изменялись — сменился только
владеющий этап, поля `reassignment` и `remaining` описывают новое условие закрытия.

**Честно про `SD1-D2-16`:** реализованная защита **строже** требования — кандидат не раскрывает ничего,
включая владельца, поэтому утечки нет и дефекта безопасности нет. Открыта нормализация правила
прозрачности (какой заводской промпт уже публичен и где нельзя обещать секретность), а не исправление
утечки.

### Три оставшихся PENDING — не дефекты D2

| Строка | Чего ждёт |
|---|---|
| `SD1-AMX-09` | вход `inspect_runtime` появится в D3, отрисованная поверхность — в D6; затем та же карта `TOOL_CAPABILITIES` подтверждается на реальном вызове |
| `SD1-D2-23` | обязательный флаг sensitivity при регистрации провайдера (`ParamSpec.secret` сейчас по умолчанию `False`) |
| `SD1-D2-24` | evidence bundle D3 (`SD1-EVD-04`) и typed settings adapter с `configured/effective/last_success/last_error_code/key_fingerprint` |

### Границы после перераспределения

Доли слайсов: **D2 — 41, D4 — 18, D5 — 21, D6 — 32**, общий итог эпика по-прежнему **182** (ни одна
строка не удалена и не добавлена). Срез D2: **33 VERIFIED, 5 READY_FOR_LIVE, 3 PENDING**.

```
--stage plan                                   → inventory=183 manual=53 scoped=0  errors=0
--stage review --slice D2 --candidate 98bc424e → inventory=183 manual=53 scoped=44 errors=3
   SD1-AMX-09, SD1-D2-23, SD1-D2-24 — mandatory not ['VERIFIED'] (got PENDING)
```

Счёт ошибок в срезе D2 уменьшился с 6 до 3 **не потому, что работа сделана**, а потому, что три строки
перестали принадлежать срезу по решению владельца. На эпик это не влияет: те же обязательства теперь
ждут закрытия в D4/D5/D6 и обязаны быть там проверены.
