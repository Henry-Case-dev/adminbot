# W6 / EVOL-SRC-READER - независимое ревью (Reviewer)

Кандидат: `feat/evol-src-reader`, коммиты `171b99c6` (код+тесты+снапшот) и `daf0385a` (отчёт Builder).
База: `5fc2ded5`. Осмотр: worktree `evol-71536a366a11-5d74b13a`; product-code не менялся,
мутации и пробы - в отдельном scratch-checkout и в `WorkspaceData/runs/.../temp-15c6aeba60`.
Контракт: `plans/features/evol/arch/source-reader-contract.md` (авторитетный).

## 0. Вердикт

**Needs Fixes.** Три блокирующих дефекта в новом коде:

1. инвариант V1.3 ("snippet - точная подстрока реальных байт") ломается на файлах
   с CRLF (ложный `verified=false`) и на не-текстовых байтах (ложный `verified=true`);
2. qualified reuse сверяет идентичность по СЫРЫМ аргументам и не видит ref/path,
   выведенные из ссылки: второй `read` по другой ссылке того же claim возвращает
   чужой commit или чужой файл как "verified", с 0 сетевыми вызовами;
3. reuse-ответ молча обрезает `snippet` до 2000 символов, но оставляет
   `truncated=false`, `retrievable_remainder_lines=0` и прежний `line_range`.

Плюс дефект §2 контракта (исходящий `set_signal` недостижим) и мелочи.

Остальное реализовано по контракту: слот 16, `additionalProperties:false`,
провайдер поверх `SafeFetcher` (второго транспорта нет), 0 новых REASON_CODES,
env-kill-switch, evidence-окно без новых потолков, follow-up с `not_checked`,
телеметрия стадий, проводка capability/evidence.

## 1. Что я лично проверил в коде

Прочитано целиком и сопоставлено с контрактом:

* `services/source_reader.py` (1948 строк): разбор URL и `parse_source_url`,
  `GitHubProvider` и порядок эндпоинтов, `read_file` / `_read_contents` /
  `_read_blob` / `_read_raw`, `build_snippet`, `_followup`, `_read_payload:1617-1681`,
  `_payload:1683`, `_error_payload:1737`;
* `services/tool_router.py:2904-3170`: `_read_source_code`, `_source_reader`,
  `_source_pointer`, `_source_reuse_payload`;
* `services/tool_schemas.py:848-1040` и `:1115-1150` (схема, канон, гейт анонса);
* `config/settings.py:1437-1459`, `services/tool_loop.py:62-85`,
  `services/capability_registry.py:757-785,872-881`,
  `services/evidence_policy.py:175-186`,
  `services/direct_chat_service.py:2384-2398`,
  `services/mca_retrieval_context.py:274-289`, `services/mca_events.py:560-600`,
  `services/tool_result.py:484-593`.

Ключевые проверенные пути: V1 (`verified = exact and kind==file and lines`, где
`exact = window.text in decode_file_text(bytes)`; `verified_url` только с commit);
граница провайдера (`services/safe_fetch.py` импортируется, второго HTTP-клиента
в модуле нет, токен только из env, `error.detail` - машинный тег); reuse
(`store` только после `verified`, `lookup` + сверка указателя); kill-switch
(гейт анонса в `active_tools`, серверный `disabled` первым делом в
`_read_source_code`, до любых вызовов).

## 2. Тесты: что читал и насколько им можно верить

`tests/test_evol_source_reader.py` - 59 тестов, прочитаны тела и ассерты.
Сильные стороны: V1 проверяется на реальных байтах фикстуры (`snippet in
FILE_MACHINE`, `sha256` от байт, `commit in verified_url`, `"1.20.1" not in
verified_url`); отказы (404, 403 с `x-ratelimit-remaining`, 403, 502, HTML,
чужой хост, SSRF-редирект) проверяют коды и отсутствие `verified_url`; reuse
проверяет `network_calls==0`, смену ref/commit, chat-isolation по токену, отказ
от "verified без байт"; телеметрия - только существующие коды; AST-инвариант
отсутствия `exec/eval/importlib/subprocess`; канон 16 и позиция в хвосте.

Повторенные мутации (каждая: scratch-checkout, правка, прогон, откат копией файла):

| # | Мутация | Мой результат |
|---|---|---|
| M1 | снята проверка `source_kind=="file"` | RED 1: `test_readme_is_read_but_never_verified` |
| M2 | reuse не сверяет `ref` | RED 2: `test_changed_ref_...`, `test_changed_commit_...` |
| M3 | снята сверка `path` в ответе `contents` | RED 1: `test_server_200_for_another_path_is_not_verified` |
| M4 | в `snippet` добавлен лишний символ | RED 3: `blob_link...`, `symbol_line...`, `big_file...` |

Вывод: заявленные мутации реальны, тесты не тавтологичны. Но покрытие слепо
именно там, где лежат мои находки: нет ни одного CRLF/не-UTF8 файла, ни одного
reuse по ССЫЛКЕ (только `repo/ref/path`), нет проверки честности обрезки на
reuse, нет проверки исходящего `set_signal`. Тест
`test_credentials_in_url_are_rejected` вакейтен: он проходит потому, что в
фикстуре нет `x.py`, а не потому, что креденшелы отвергнуты (см. §5, N4).

Регрессионный фон: 949 тестов в 22 файлах, затронутых обновлением канона 15->16,
зелёные (412 + 537). `tools/er65_prompt_segment_snapshot.py --check` -> OK
(27 стадий / 58 сегментов, два процесса байт-в-байт). Промпт-канон не изменён.
Предсуществующие падения базы не пересчитывал: все мои находки в новом коде и
от базы не зависят.

## 3. Мои независимые пробы (фактические результаты)

Все - на фикстурах через `httpx.MockTransport` и подменённый DNS, без сети.

| # | Что подано | Ожидание | Факт |
|---|---|---|---|
| A | `ParallelLogic.java` с CRLF, `read repo+ref+path` | `verified=true` | `status=ok`, `verified=False`, `line_range=[1,13]`, поля `error` нет, причина не указана |
| B | два `read` по ссылке: `/blob/main/...`, затем `/blob/1.20.1/...`, один `claim` | новый fetch по 1.20.1 | `reused=true`, `ref=main`, `commit=0123...` (от main), `network_calls=0`, `verified=true` |
| C | то же, вторая ссылка на ДРУГОЙ файл `ParallelConfig.java` | чтение запрошенного файла | `path=...ParallelLogic.java`, `reused=true`, `verified=true`, `network_calls=0`, `chanceLimit` в snippet нет |
| D | 1200 строк, бюджет 8000: первый read и повторный | повторный отдаёт то же и ту же честную обрезку | 1-й: `snippet_chars=9983`, `line_range=[1,510]`, `truncated=true`, `remainder=690`; 2-й: `snippet_chars=2000`, `line_range=[1,510]`, `truncated=false`, `remainder=0` |
| E | 404 по пути | ToolResult error и исходящий сигнал §2 | `error=source_missing`, `error_detail.code=source_missing`, `take_signal(ctx)` -> None |
| F | `path` указывает на каталог (`contents` -> JSON-массив) | не verified, честный вид источника | `status=error`, `error=source_missing`, `detail=path_or_ref_not_found` (каталог назван "отсутствующим файлом") |
| G | kill-switch ON (анонс) -> OFF -> вызов | инструмент не анонсирован, вызов `disabled`, 0 сети | `announced_off=False`, `status=disabled`, `calls=0` |
| H | дерево с `truncated=true` | честный `not_checked` | `status=ok`, `verified=true`, `not_checked.reason=tree_truncated` (честно) |
| I | бинарные байты (PNG-заголовок, NUL, 0xFF), `path=assets/logo.bin` | не должно быть "verified source" | `status=ok`, `verified=True`, `snippet` содержит NUL и служебные символы |
| J | ссылка `user:pass@github.com/...` на существующий файл | отказ до сети (§5) | `status=ok`, `verified=true`, контакт только `api.github.com`, креденшелы отброшены |

I и A - один корень (§4.1). B и C - один корень (§4.2).

## 4. Блокирующие находки

### F1 (blocker, Builder) - V1.3 ломается на реальных байтах: CRLF даёт ложный `verified=false`, не-текст даёт ложный `verified=true`

Требование: §1.2 V1.2 и V1.3 контракта; строки L01198, L01200, L01228, L01232.
Место: `services/source_reader.py:838-848` (`decode_file_text`: при ошибке UTF-8
откат в **latin-1**, хотя docstring обещает "честный отказ на не-utf8"),
`:851-855` (`split_lines` -> `str.splitlines()`, теряет CR),
`:1004` (`text = "\n".join(...)`), `:1632` (`exact = window.text in text`).
Воспроизведение: пробы A и I. `window.text` склеивается через `\n`, поэтому для
CRLF-файла он не является подстрокой исходного текста, и `verified=false`: модель
получает "файл не подтверждён" про реально прочитанный файл. Latin-1 всегда
"декодирует", поэтому бинарные байты дают `verified=true` с NUL и служебными
символами вместо кода.
Влияние: CRLF-исходники обычны (в этом же репозитории 16 файлов закоммичены с
CRLF; любая Windows-ориентированная кодовая база), для них основная возможность
слайса молча не работает; на бинарном пути модель может получить "verified"
мусор. В обе стороны рушится смысл единственного флага, на который опирается
Writer.
Минимальная правка: собирать `snippet` из исходного текста по смещениям строк
(сохраняя реальные переводы строк) либо нормализовать текст и байты одним
способом перед сверкой; `verified` выдавать только при строгом декодировании
(UTF-8) и отсутствии NUL/управляющих байтов, иначе честный не-verified ответ с
причиной.
Перепроверка: два теста - CRLF-файл (`verified=true`, `snippet` подстрока
исходных байт) и бинарный файл (`verified=false` + честный код); плюс повтор проб
A и I.

### F2 (blocker, Builder) - reuse не сверяет ref/path из ссылки: чужой commit или файл как `verified`

Требование: V1.1 ("точная идентичность `(repo, commit, path)`"), V1.4, §3.3
контракта (смена версии инвалидирует), L01208, L01220.
Место: `services/tool_router.py:2977-2979` (`identity` строится из СЫРЫХ
аргументов `repo/ref/path`), `:3120-3129` (сверка пропускается, если поле
пустое), `:3130-3145` (готовый `verified=true`).
Воспроизведение: пробы B и C. Модель передаёт ссылку (схема прямо разрешает:
"url is enough, no repo needed"), claim тот же, все проверки пропускаются,
ответ отдаёт прежние `commit`/`path`/`snippet` с `verified=true` и
`network_calls=0`.
Влияние: бот может "прочитать" версию `main`, когда спросили `1.20.1`, или отдать
чужой файл, и сослаться на него как на проверенный. Это ровно тот класс ошибки
(§1.1 ТЗ: "назвал вероятный класс, но не прочитал исходник"), против которого
сделан слайс.
Минимальная правка: считать identity из фактически разрешённой идентичности
(`parse_source_url(url)` -> repo/ref/path поверх явных аргументов) и требовать
совпадения `pointer.ref` / `pointer.path` / `pointer.commit`; при расхождении -
обычный fetch.
Перепроверка: тест "тот же claim, две разные ссылки (другой ref и другой файл) ->
второй вызов не reuse"; повтор проб B и C.

### F3 (blocker, Builder) - reuse-ответ скрывает обрезку: `truncated=false`, `remainder=0`, старый `line_range`

Требование: §1.1 Evidence Contract (объём и обрезка), L01200. Существующий
прецедент в том же файле: `fetch_article` на reuse ставит `truncated: True` и
`remainder_chars` (`tool_router.py:2675-2681`).
Место: `services/tool_router.py:3044` (`snippet=...[:2000]`) и `:3146-3152`
(truncation с `truncated: False`, `effective_limit: 0`,
`retrievable_remainder_lines: 0`, `limit_source: reuse`), при этом `line_range`
берётся из указателя.
Воспроизведение: проба D. Первый ответ 9983 символа, строки 1-510,
`truncated=true`, остаток 690; повторный - 2000 символов с теми же строками 1-510
и `truncated=false`, остаток 0.
Влияние: модель получает около 20 процентов текста, но метаданные утверждают,
что обрезки нет и ничего не осталось; на этих метаданных строятся выводы о
поведении кода.
Минимальная правка: либо хранить полный `snippet`, либо на reuse пересчитывать
честные `truncated` и `retrievable_remainder_lines` (в символах и строках) и
приводить `line_range` к доставленному фрагменту.
Перепроверка: сценарий D (ожидание `truncated=true` и ненулевого остатка на
повторном чтении).

## 5. Неблокирующие замечания (в тот же проход)

* **N1.** §2 контракта требует переносить `SafeFetchError` в исходящий сигнал
  `_tool_result.set_signal`; ветка `tool_router.py:3051` (`if isinstance(error,
  dict)`) недостижима, потому что `_error_payload:1737` кладёт `error`
  строкой-кодом (`error_detail` рядом). Проба E: `take_signal -> None`.
  Пользовательски не видно (код уже в payload), но это мёртвый код и
  невыполненное требование §2. Правка: читать `error_detail`.
* **N2.** Каталог вместо файла (`contents` -> массив) отдаётся как
  `source_missing/path_or_ref_not_found` (проба F), то есть "файла нет", хотя
  честный ответ "это каталог". `ERR_UNSUPPORTED_KIND` глушится в
  `_resolve_identity:1366`. Пустой файл - тоже `source_missing` (`empty_file`).
* **N3.** `_REASON_FOR_CODE[ERR_UNSUPPORTED_KIND] = "capability_not_ready"`:
  такого значения нет в `mca_events.REASON_CODES` (314 значений). Путь почти
  недостижим, тест `test_stage_events_use_existing_reason_codes` его не
  покрывает, поэтому "0 новых кодов" держится на непроверенном пути. Взять
  существующий код или не эмитить вовсе.
* **N4.** `test_credentials_in_url_are_rejected` вакейтен: с существующим файлом
  тот же вход даёт `ok/verified=true` (проба J). Креденшелы молча отбрасываются
  (утечки нет: запросы идут только на `api.github.com`), но тест утверждает не
  то, что проверяет.
* **N5.** Обновляя пин-тесты, Builder перекодировал переводы строк в 16 файлах
  (диф 9630 строк против 3841 при `-w --ignore-cr-at-eol`). Контент корректен,
  но шум мешает параллельным полосам и ревью; просьба вернуть прежние окончания.
* **N6.** Мелочи метаданных: `capability_registry` указывает исполнителя
  `services.source_reader`, хотя обработчик живёт в `tool_router`;
  `safe_log_ref` не используется; `files[].verified` в follow-up не применяет
  проверку `source_kind=="file"` (сегодня безвредно из-за фильтра расширений).

## 6. Отклонения §4 отчёта Builder - вердикт

1. **Порядок кандидатов ref (короткий первым).** Контракт говорит "длинный
   первым". Требование ТЗ "правильно разрешать ветки со слэшем" выполняется при
   любом порядке (`feature/x` стоит одну лишнюю пробу), а "длинный первым" жёг
   бы квоту на обычных ссылках. **Приемлемая деталь реализации**; просьба
   зафиксировать это строкой в контракте, чтобы следующий ревьюер не счёл
   дрейфом. Замечание на будущее: если в репозитории есть и ветка `feature` с
   путём `x/...`, и ветка `feature/x`, инструмент молча выберет первую; в таких
   редких случаях стоило бы отдавать `ambiguous`.
2. **События `mca07_source_<stage>` вместо одного `mca07_source_read`.**
   Общий эмиттер `mca_retrieval_context.emit_stage_event` строит имя как
   `mca07_` + stage и кладёт стадию отдельным полем; требование "стадии
   различимы" (§1.2.5) иначе не выполнить. **Приемлемо.**
3. **`snippet` без префиксов номеров строк.** §1.1 буквально просит "код с
   номерами строк", но V1.3 требует "точную подстроку, проверяемую в коде".
   Префиксы сделали бы инвариант непроверяемым и создали вторую копию текста;
   номера отдаются `line_range` и `files[].line_range`. **Приемлемо** (V1.3 -
   содержательный инвариант).
4. **`error` строкой-кодом плюс `error_detail`.** Требуется конвейером
   (`tool_result._payload_error_code` читает `payload["error"]`), иначе пришлось
   бы править `classify_output`. **Приемлемо**, но именно эта замена сделала
   мёртвой ветку исходящего сигнала (N1) - чинится в роутере, не в схеме.
5. **Порядок эндпоинтов `contents -> blobs -> raw`.** Набор тот же, что в §2 и
   §8, каждый шаг пишется в `provenance.endpoint`; при известном blob-sha из
   дерева `blobs` идёт первым. **Приемлемо.**
6. **`no_relevant_results` только в payload, в телеметрию `retrieval_empty`.**
   Значения `no_relevant_results` в `mca_events.REASON_CODES` нет (проверено:
   314 значений), `retrieval_empty` - существующий канон. **Приемлемо** (иначе
   это был бы новый код).
7. **`METERED_EVIDENCE_READ_ONLY` по ER-08.** Решение владельца прямо про
   read-only проверки без "денежного" счётчика; инструмент тратит 0 LLM-токенов
   на чтение, анти-петлевые границы (6 вызовов на ход, дедуп x2,
   `SOURCE_READ_MAX_REQUESTS=8`) сохранены. **Приемлемо.** Остаточный риск: до
   ~48 запросов к GitHub за ход без токена (60 в час на IP); отказ будет честным
   `rate_limit`, но квоту это жжёт (см. §7).

## 7. Границы доказательства и живые проверки (после деплоя; не гейт приёмки)

`live_required=false, live_when=preprod` (карта, строка EVOL-SRC-READER).
Полностью доказано офлайн: разбор форм URL (blob, tree, raw, api, issues, pull),
чтение байт и `verified` по LF-фикстурам, path-сверка 200-ответа, README не
источник, отказы 403/404/429-семантика/5xx/HTML/SSRF/размер, follow-up с
`not_checked`, kill-switch, окно evidence, телеметрия, доступность capability.

Требуют живого вызова:

1. Реальный кейс GregTech (`1.20.1`, `ParallelHatchPartMachine`,
   `GTRecipeModifiers.hatchParallel`, `ParallelLogic`, `RecipeRunner`,
   `ChanceLogic`) - L01210: `verified=true`, commit-pinned ссылка с реальным
   commit, правильные строки, цепочка follow-up.
2. Анонимная квота: сколько запросов реально уходит на исследование
   (commits+tree+contents примерно 3-5), поведение `x-ratelimit-remaining`,
   честный `rate_limit` на исчерпании; подтвердить, что
   `raw.githubusercontent.com` не тратит REST-квоту.
3. Secondary rate limit (403 без `retry-after`) -> `rate_limit`, без ретраев.
4. Дерево больше 100 000 записей или 7 МБ: `truncated=true` ->
   `not_checked.reason` и отсутствие ложного "файла нет". Деградации через
   `/contents/<dir>`, описанной в §3 контракта, в коде нет: это остаток, не
   блокер (честность сохранена).
5. Ветка со слэшем в реальном репозитории (`feature/x`): разрешение и одна
   лишняя проба; проверить, что редкая коллизия не подменяет файл молча.
6. CRLF-исходник из реального репозитория (после фикса F1): `verified=true`.
7. Приватный репозиторий с токеном (если включат): `scope=chat`, отсутствие
   межчатового reuse, токен не в payload и логах, `auth_failed` при отказе.
8. Маршрутизация в живом диалоге (L01206, L01211, L02360): "где в этом моде
   считается параллельный выход", "найди файл X в репозитории" -> инструмент
   вызван, Writer опирается на `verified`, не говорит "посмотрел код" без байт.

## 8. Строки карты

В слайсе `EVOL-SRC-READER` 61 строка: 30 `required` (все PENDING), 5 `duplicate`
PENDING и 26 `VERIFIED` строк чужих слайсов. Builder карту не менял.

Сейчас привязывать нельзя: F1-F3 бьют по V1, reuse и честности evidence, значит
по L01184, L01198, L01200, L01208, L01220, L01228, L01232, L01234 и по
производным L02230, L02360 доказательство неполно.

Правило для PM после исправления и повторного ревью:

* привязывать к НОВОМУ кандидату (не `daf0385a`), evidence-пути - на отчёт и на
  конкретные тесты;
* строки L01196, L01197, L01199, L01207, L01209, L01231 (и L01217, L01218,
  L01233 в части payload) можно закрыть по существующим доказательствам, если
  фикс не трогает соответствующие механизмы;
* L01206, L01211, L02360 - только "в части инструмента" с явной пометкой, что
  маршрутизация LLM проверяется живым диалогом (п. 8 §7); без такой пометки
  строка не должна становиться VERIFIED;
* L01219, L01221 - не этот слайс (промпт-канон байт-в-байт, ER-65 snapshot OK);
* L02401 - вне рамки слайса (локальный файл пользователя);
* 5 `duplicate` строк закрывать нельзя: у них тот же статус, что у родительских.

Гейт: `requirements_gate.py check --stage review --slice EVOL-SRC-READER
--candidate daf0385a` сейчас FAIL (57 ошибок: 30 обязательных PENDING, PENDING у
`ER-50` и `ER-S03`, плюс "no evidence bound to reviewed candidate" у 20+ строк
других слайсов). Это ожидаемо до привязки PM. Отдельно: `deployed_commit` карты
(`6645ae8d`, 2.58.148) расходится с указанной в рамке базой `5fc2ded5`
("задеплоено 2.58.149"); DevOps/PM нужно свести это до релиза, иначе approval
привязан к неверной базе.

## 9. Что перепроверить при повторном ревью

1. Пробы A и I (CRLF и бинарный файл) - оба направления V1.
2. Пробы B и C (reuse по ссылке с другим ref или файлом) - должен идти fetch.
3. Проба D (reuse после обрезки) - честные `truncated`, остаток, `line_range`.
4. Проба E - `take_signal` отдаёт код, стадию и `retryable` при отказе.
5. Точечно: N2 (каталог и пустой файл), N3 (код причины вне словаря),
   N4 (вакейтный тест креденшелов).
6. Полный прогон `tests/test_evol_source_reader.py` + 22 затронутых файла +
   `er65 --check` (сейчас: 59/59, 949 в 22 файлах, OK).

---

# Re-review 2 (после фикса B1/B2/B3)

Кандидат: `004d59f3` (фикс поверх `daf0385a`; исходный код слайса - `171b99c6`), база `5fc2ded5`.
Проверялись ТОЛЬКО мои находки Re-review 1 + их окружение (соседние пути, которые
фикс реально задел). Product-code не менялся; мутации - в отдельном
scratch-checkout (`evol-src-reader-rereview2-...`, удалён после прогонов).

## R2.0. Вердикт

**Approved** по B1/B2/B3 и по всем мелочам N1-N5; одна неблокирующая остаточная
находка R-1 (узкая, требует 2 строк правки в следующем касании). Все три моих
прошлых блокера воспроизведённо закрыты, тесты ловят их регресс (3 мои мутации
дают RED).

## R2.1. Пробы (фактические числа)

| # | Что подано | Ожидание | Факт на `004d59f3` |
|---|---|---|---|
| B1a | `ParallelLogic.java` с CRLF, `read repo+ref+path+symbol` | `verified=true`, snippet - точная подстрока с `\r\n`, верные строки | `verified=True`, `line_range=[1,13]`, `file_total_lines=13`, `"\r\n" in snippet=True`, `snippet in исходный_текст=True`, snippet начинается с `'package acme;\r\n\r\npublic class...'` |
| B1b | PNG/NUL байты, `path=assets/logo.png` | не verified, честный `unsupported` + причина | `status=unsupported`, `verified=False`, `reason=binary_content`, `snippet_chars=0` |
| B1c | те же байты в cp1251 (не-UTF-8) | не verified, никакого latin-1 | `status=unsupported`, `reason=invalid_encoding`, `snippet=''` |
| B1d | UTF-8 с кириллицей, `symbol=x` | `verified=true`, верные строки | `verified=True`, `line_range=[1,6]`, `total=6`, `exact=True`, `symbol_found=True` |
| B2a | тот же claim, `/blob/main/...` затем `/blob/1.20.1/...` | второй - не reuse, читается запрошенная версия | `second.reused=False`, `second.ref=1.20.1`, `verified=True`, реальные вызовы |
| B2b | тот же claim, ссылка на другой файл `ParallelConfig.java` | не отдавать прежний файл | `path=.../ParallelConfig.java`, `reused=False`, snippet содержит `chanceLimit` |
| B2c | ветка со слэшем `feature/x`, та же ссылка дважды | повтор - reuse без сети | `first.ref=feature/x`, `verified=True`; `second.reused=True`, `network_calls=0` |
| B3 | 1200 строк, бюджет: первый read и повтор | те же числа, `limit_source=reuse` | 1-й: `9983` симв., `[1,510]`, `truncated=True`, `rem=690`, `limit=10000`, `src=call_budget`; 2-й: `9983`, `[1,510]`, `truncated=True`, `rem=690`, `src=reuse`, `reused=True`, `calls=0` |
| N1 | 404 и 502 | `take_signal` с кодом/стадией/reason/retryable | 404: `{error_code: source_missing, stage: discover, reason: repo_not_found, retryable: False}`; 502: `{error_code: provider_unavailable, stage: fetch, reason: '', retryable: True}`; classify совпадает |
| N2a | `path` указывает на каталог | отдельный статус, не «файла нет» | `status=unsupported`, `reason=path_is_directory`, `source_kind=directory` |
| N2b | пустой файл (0 байт) | отдельный статус | `status=unsupported`, `reason=empty_content`, `verified=False` |

## R2.2. Мои мутации (откат фикса -> RED)

Scratch-checkout на `004d59f3`, копия файла, правка, прогон, возврат копией.

| # | Что откатил | Результат |
|---|---|---|
| MA (B1) | `split_lines`: `text.split("\n")` -> `text.splitlines()` (съедает `\r`) | RED 2: `test_crlf_file_verifies_and_snippet_is_exact_substring`, `test_decode_rule_is_strict` |
| MB (B2) | `_source_pointer_matches` -> `return True` | RED 4: `test_reuse_by_link_with_other_ref_fetches`, `test_reuse_by_link_to_other_file_fetches`, `test_changed_ref_...`, `test_changed_commit_...` |
| MC (B3) | reuse-truncation: `truncated` -> `False` | RED 1: `test_reuse_keeps_honest_truncation_metadata` |

## R2.3. Прогоны

* `tests/test_evol_source_reader.py` - **74 passed** (было 59; добавлены
  TestByteSemantics, TestOutboundSignal, reuse-by-link, честная обрезка,
  словарный тест кодов).
* 22 затронутых файла (пины канона 15->16) - **949 passed**.
* Соседние контуры (evidence routing/window, capability registry/intent,
  mca02 safe fetch) - **370 passed**.
* `py tools/er65_prompt_segment_snapshot.py --check` - **OK** (27 стадий /
  58 сегментов, байт-в-байт, два процесса).

## R2.4. Статус мелочей Re-review 1

* **N1 (сигнал §2)** - закрыт: роутер читает `error_detail` (dict), dict-форма
  оставлена совместимостью; проба N1 выше.
* **N2 (каталог/пустой файл)** - закрыт: `unsupported` с причинами
  `path_is_directory` / `empty_content`, `source_kind=directory` для каталога.
* **N3 (`capability_not_ready`)** - закрыт: непригодная форма ответа теперь
  `parse_error` (существующий код), добавлен словарный тест
  `test_every_mapped_reason_code_exists_in_dictionary` (все значения
  `_REASON_FOR_CODE` есть в `mca_events.REASON_CODES`).
* **N4 (вакейтный тест креденшелов)** - закрыт: тест проверяет фактический
  список хостов и `guarded_target` -> `credentials_in_url`, плюс отсутствие
  `user:`/`pass@` в payload.
* **N5 (переводы строк в 16 файлах)** - закрыт: файлы снова в CRLF как в базе
  (`git show HEAD:...` даёт CRLF), диф по базе сократился с 9630 до 4457 строк,
  при `--ignore-cr-at-eol` остаются только реальные правки пинов.
* **N6** - частично: исполнитель capability исправлен на `services.tool_router`;
  `safe_log_ref` удалён; `files[].verified` в follow-up теперь учитывает
  `source_kind=="file"` и не выдаёт `verified_url` при не-verified.

## R2.5. Остаточная находка R-1 (неблокирующая, Builder/backlog)

Если запрос идёт БЕЗ явного `path`/`ref` (`read repo=... symbol=chanceLimit`) и
по тому же claim уже прочитан файл, reuse отдаёт прежний файл: `status=ok`,
`verified=true`, `reused=true`, `path=.../ParallelLogic.java`,
`symbol=compute`, `symbol_found=true` - при том, что запрашивался
`symbol=chanceLimit`. Видно из пробы B2d (payload сам показывает `path`,
`symbol`, `reused` и строку `reuse: ...`).

Почему не блокирую: явный адрес (path/ref) в запросе не задан и не подменяется;
claim тот же (та же исследовательская сущность); payload честно перечисляет
доставленную идентичность; три обязательные проверки B2 из рамки проходят.
Тем не менее `symbol_found=true` для НЕзапрошенного символа вводит в
заблуждение.

Минимальная правка (следующее касание `_source_pointer_matches`): не разрешать
reuse, если `identity["symbol"]` и `pointer["symbol"]` оба непусты и различаются
(2 строки + 1 тест). Либо явно отдавать в payload `symbol_requested` рядом с
`symbol`.

## R2.6. Привязка строк карты (правило для PM)

Кандидат для привязки: **`004d59f3`**. Карта Builder-ом не менялась; гейт
`--stage review --slice EVOL-SRC-READER --candidate 004d59f3` всё ещё FAIL
(57 тех же ошибок: 30 обязательных PENDING + PENDING у `ER-50`/`ER-S03` +
"no evidence bound" у строк других слайсов) - это работа PM, не Builder.

Можно закрывать по этому кандидату (evidence: этот отчёт + Re-review 2 +
`tests/test_evol_source_reader.py`):
L01184, L01185, L01186, L01196, L01197, L01198, L01199, L01200, L01207, L01208,
L01209, L01223, L01228, L01229, L01230, L01231, L01232, L01234, L02230.

Закрывать только «в части инструмента/payload» с явной пометкой:
L01210 (структурно: ни одного имени из кейса в runtime; реальный прогон GregTech
- живая проверка), L01217, L01218, L01233 (в payload нет цитат и хронологии;
поведение LLM не доказывается), L01220 (смысл статуса; добавить note про R-1).

Только с живой проверкой (LLM-маршрутизация, не код слайса):
L01206, L01211, L02360.

Не этот слайс: L01219, L01221 (промпт-канон байт-в-байт, ER-65 OK),
L02401 (локальный файл пользователя).
5 `duplicate` строк - по статусу родительских.

Живые проверки - без изменений из Re-review 1 (§7): реальный кейс GregTech,
анонимная квота и `x-ratelimit-remaining`, secondary rate limit, дерево
truncated, ветка со слэшем в реальном репо, CRLF-файл реального репо (теперь
ожидается `verified=true`), приватный репо с токеном, маршрутизация в диалоге.
Остаток, не блокер: деградации через `/contents/<dir>` при `tree_truncated` в
коде нет (честный `not_checked` есть).

Отдельно для DevOps/PM: `deployed_commit` карты (`6645ae8d`, 2.58.148) всё ещё
расходится с базой `5fc2ded5` («2.58.149»); свести до релиза.
