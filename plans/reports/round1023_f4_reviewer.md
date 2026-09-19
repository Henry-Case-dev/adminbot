# Reviewer — раунд 10.23, F4 `dynamic-anticliche-cache-round1023`

- **Шаг:** 5 раунда 10.23, строгий аудит F4.
- **Итерация 1** (коммит `766f8a5`, `766f8a5^ == 2179a1e`): **Changes Requested** (H1, M2, M3 + Low L1–L8). Полный pytest — **7186 passed / 0 failed**.
- **Итерация 2** (коммит `4e05579`, `4e05579^ == 67278f2`): **Approved** — H1/M2/M3 и L1–L8 закрыты по существу; новых блокеров нет. Детали — в разделе «Итерация 2» в конце отчёта.
- **Коммит (итерация 1):** `766f8a5`, ветка `master`.
- **Baseline спеки:** HEAD `731a845`; pytest 6962/0; каталог 439/409/414/92/90/20; SQLite v12; прод `a8a6437`.
- **Проверено:** `plans/features/dynamic-anticliche-cache-round1023/{spec.md,ADR-1023-4.md,tasks.md}`,
  `plans/features/round1023-architecture.md`, `plans/reports/round1022_scanner_audit.md:139` (S10.22-4b),
  `git show 766f8a5 --stat`, `git diff 766f8a5^ 766f8a5`.
- **Тесты:** целевые `test_anticliche_round1023` — **59 passed**; батч
  `test_negative_constraints_round1022 + test_pg_db + test_param_catalog + test_de_robotization_round1021 +
  test_outgoing_guard_round1022` — **169 passed**; **полный pytest — 7186 passed / 0 failed** (95.7 с).
- Секреты из `plans/current_task.md` не цитируются (R18). Прод-этапы T-2135 не выполнялись.

---

## Статус: Changes Requested

Ядро фичи собрано правильно: динамические правила действительно питают **детектор** (не scrubber и не промпт),
`FORBIDDEN_CLICHE_PATTERNS` не подменён, `outgoing_guard.py` не тронут, промпт-константы не менялись, DDL
идемпотентен, RBAC на месте. Но по трём пунктам фича недоведена до заявленного контракта, и один из них бьёт
ровно по обещанию fail-open («предыдущий кэш сохраняется»), которое для этой фичи и есть смысл существования.

Возврат на доработку. Ниже — точные дефекты и что именно чинить.

---

## Findings

### [Severity: High] H1 — Валидный, но вырожденный ответ LLM затирает предыдущий кэш (нарушение fail-open)

- **Файлы:** `services/anticliche_worker.py:275-290` (`refresh`), `services/anticliche_worker.py:120-148`
  (`build_patterns`), `services/anticliche_cache.py:150-167` (`write_patterns`).
- **Проблема:** если LLM вернула **валидный** JSON, из которого после нормализации/дедупа/фильтра
  хардкод-дублей не осталось ни одного правила (`{"patterns": []}`; либо все фразы — эхо захардкоженного
  списка, что для источника «признаки ИИ-письма» — самый вероятный сценарий), то:
  `build_patterns(...) -> []` → `write_patterns(pg, [], ...)` **перезаписывает singleton пустым списком**,
  `version+1`, `last_status='ok'`.
- **Проверено программно:**
  `build_patterns([{"phrase":"подводя итог"},{"phrase":"надеюсь, что помог"}]) == []`.
- **Почему это важно:** spec §2.1 и R3 прямо обещают «сбой источника/LLM/записи → **предыдущий кэш сохраняется**».
  Вырожденный, но «успешный» ответ — это штатный сбой нестабильного внешнего LLM-контура. Итог: динамический
  фильтр молча умирает минимум на неделю (до следующего тика), а в UI/`GET /api/anticliche` админ видит
  бодрое `last_status=ok, count=0`. Захардкоженный детектор остаётся, но фича, за которую отвечает F4, не работает.
  Ровно тот класс тихих потерь, который митигация R3 обязана была исключить.
- **Required fix:** в `AntiClicheWorker.refresh` после `patterns = build_patterns(entries)` добавить guard:
  если `not patterns` — **не вызывать** `write_patterns`; сохранить прежнюю строку, выставить
  `last_status` (напр. `parse_error` или новый `empty`) через `anticliche_cache.mark_status(pg, ...)` и
  вернуть `{"status": "parse_error"/"empty", "count": 0, "version": <текущая версия>, "source": source_id}`.
  Пустая запись по-прежнему допустима **только** через явный `PUT` (ручная очистка). Обязательный регресс-тест:
  в PG лежит непустой кэш → LLM возвращает `{"patterns":[]}`/эхо хардкода → `status != ok` и
  `store.row["patterns"]` не пуст.

### [Severity: Medium] M2 — Контракт `dynamic_rules: Iterable` ломается на итераторе: ретраи теряют динамическую детекцию

- **Файлы:** `services/negative_constraints.py:295-331` (`find_forbidden_cliches`), `:338-419`
  (`verbalize_validated`), вызовы детектора `:379` и `:403`.
- **Проблема:** один и тот же объект `dynamic_rules` прокидывается в детектор на попытке 0 и на каждом ретрае.
  Аннотация — `Iterable[DynamicClicheRule]`, т.е. генератор/итератор формально допустим. После первого
  `_dynamic_hits` генератор исчерпан, и на ретраях динамические правила **не находятся вовсе**.
- **Проверено программно (генератор):**
  `rules = (r for r in [build_dynamic_rule("секретный штамп")])`;
  первый `find_forbidden_cliches(...) -> ['dyn_e780066d']`, второй → `[]`;
  `verbalize_validated(...)` с генератором завершился `retries=1, hits=[]` — второй текст с тем же клише
  признан «чистым».
- **Почему это важно:** любой будущий вызывающий, который передаст генератор (что не запрещено сигнатурой),
  получит ложный отрицательный вердикт: клише в ответе останется, а история/статистика скажет «чисто».
  Сейчас оркестраторы передают кортеж из `get_rules()`, поэтому дефект латентный — но публичный контракт
  должен либо честно требовать `Sequence`, либо быть безопасным.
- **Required fix:** материализовать один раз в начале:
  `dyn = tuple(dynamic_rules) if dynamic_rules else ()` — в `find_forbidden_cliches` (и/или `verbalize_validated`)
  и работать только с `dyn`. Добавить регресс-тест с генератором: ретрай обязан снова увидеть динамическое правило.

### [Severity: Medium] M3 — Фикс S10.22-4b неполный: пробел перед запятой снова даёт ложный `as_ai`

- **Файл:** `services/negative_constraints.py:73-81` (comma-lookbehind ветки правила `as_ai`).
- **Проблема:** добавленные `(?<!\bон,\s)`, `(?<!\bлюди,\s)` и т.д. жёстко требуют «местоимение+запятая+пробел».
  Вариант с пробелом перед запятой (`Он , как ИИ`, `Люди , как …`) — типичный дефект набора — не покрыт и
  снова даёт `['as_ai']`, потому что `_normalize` схлопывает пробелы, но не удаляет пробел перед запятой.
- **Проверено программно:**
  `find_forbidden_cliches("Он , как искусственный интеллект, не устаёт") == ['as_ai']`,
  `find_forbidden_cliches("Люди , как ИИ") == ['as_ai']`
  (при этом `"Он, как ИИ"` и `"Он,  как ИИ"` → `[]`, первое лицо `"Я, как ИИ"` → `['as_ai']` — сохранено).
- **Почему это важно:** это тот же класс ложного срабатывания, ради закрытия которого делался фикс: до двух
  полных регенераций Вербализатора (стоимость/латентность) на обычном тексте с опечаткой. Признавать S10.22-4b
  закрытым до устранения этого варианта нельзя.
- **Required fix (Python `re` не умеет lookbehind переменной длины):** добавить к третьеличному правилу
  симметричные fixed-width варианты с пробелом перед запятой: `(?<!\bсебя\s,\s)`, `(?<!\bон\s,\s)`,
  `(?<!\bона\s,\s)`, `(?<!\bоно\s,\s)`, `(?<!\bэто\s,\s)`, `(?<!\bлюди\s,\s)`, `(?<!\bчеловек\s,\s)`.
  Дополнить `TestS1022_4b` кейсами `"Он , как искусственный интеллект"` / `"Люди , как ИИ"` → `[]`.

### [Severity: Low] L1 — Мёртвая константа `_ALLOWED_STATUSES`

- **Файл:** `services/anticliche_worker.py:66-68`.
- **Проблема:** `_ALLOWED_STATUSES` заведена, но нигде не используется (ни валидации `last_status`, ни `mark_status`).
- **Required fix:** либо удалить, либо применять в `anticliche_cache.mark_status`/`write_patterns` как whitelist
  R17-safe статусов.

### [Severity: Low] L2 — `apply_manual` — мёртвый дубль логики ручной правки

- **Файлы:** `services/anticliche_worker.py:300-307` против `web/api/anticliche.py:118-123`.
- **Проблема:** API `PUT /api/anticliche` заново реализует `build_patterns + write_patterns(source="manual", ...)`,
  а `AntiClicheWorker.apply_manual` делает ровно то же, но вызывается только из собственного теста. Две копии
  одной бизнес-логики неизбежно разъедутся (например, когда H1-фикс добавит guard — он будет не в обоих местах).
- **Required fix:** либо провести PUT через `apply_manual`, либо удалить метод. Один путь ручной правки.

### [Severity: Low] L3 — `fetched_at` искажается ручной правкой и статусными апдейтами

- **Файл:** `services/anticliche_cache.py:34-44` (`fetched_at = EXCLUDED.fetched_at = now()` при любом upsert),
  `:47-49` (`mark_status` двигает `updated_at`); spec §2.2 трактует `fetched_at` как «время забора источника».
- **Проблема:** ручная правка (`source='manual'`) выставляет `fetched_at=now()`, хотя забора источника не было;
  `mark_status` на ошибке тоже двигает `updated_at`. Метаданные в UI будут вводить в заблуждение.
- **Required fix:** для ручной правки сохранять прежний `fetched_at` (или обнулять); `mark_status` не трогать
  `updated_at` либо ввести отдельный `status_at`.

### [Severity: Low] L4 — Нет верхней границы длины `phrase` в API-входе

- **Файл:** `web/api/anticliche.py:33-39` (`PatternIn.phrase: str = ""`).
- **Проблема:** `_MANUAL_INPUT_CAP=200` ограничивает число элементов, но не их размер. 200 строк неограниченной
  длины прогоняются через `_normalize`/regex до проверки длины — админ-триггерный расход CPU/памяти.
- **Required fix:** `phrase: str = Field(default="", max_length=500)` (и `origin` — `max_length=200`).

### [Severity: Low] L5 — Учёт бюджета фона неточен

- **Файл:** `services/anticliche_worker.py:246-255` (call-consume до fetch), `:291-296` (token-consume только после успешной записи).
- **Проблема:** неудачный fetch/parse списывает LLM-call, хотя вызова не было; при `parse_error`/`llm_error`
  токены не списываются, хотя вызов состоялся. Учёт занижает/завышает расход.
- **Required fix:** списывать call непосредственно перед `_call_llm` и токены — сразу после ответа LLM
  (до parse/write), независимо от исхода разбора.

### [Severity: Low] L6 — Нет тест-гаранта «фразы не в промпте» и «EXTRACT_SYSTEM_PROMPT не перечисляет клише»

- **Файлы:** `services/anticliche_worker.py:52-64` (`EXTRACT_SYSTEM_PROMPT`);
  `tests/test_anticliche_round1023.py` (покрытия нет).
- **Проблема:** spec §5 требует тест-гарант: (а) промпт извлечения не цитирует сами клише; (б) динамические
  фразы не попадают в `system`/`user` сообщения Вербализатора. Тест `test_dynamic_rule_triggers_retry` не
  проверяет содержимое переданных сообщений; `EXTRACT_SYSTEM_PROMPT` вообще не проверяется.
- **Required fix:** добавить: (1) assert, что маркеры тропов (`"как ИИ"`, `"надеюсь, помог"` и т.п.) отсутствуют
  в `EXTRACT_SYSTEM_PROMPT`; (2) тест, что при срабатывании динамического правила ни одно сообщение, переданное
  в `generate_call`, не содержит фразы динамического правила (только статичный `CLICHE_RETRY_SYSTEM_PROMPT`).

### [Severity: Low] L7 — Расхождение сквозного архитектурного документа с ADR

- **Файл:** `plans/features/round1023-architecture.md:202`.
- **Проблема:** таблица ступеней указывает `prompt_style_blocks.py` ступень «**F3 → F4** (… F4 — динамический
  блок клише)». Это прямо противоречит `ADR-1023-4` D1/D4 и spec §5 (F4 промпты **не** трогает). Коммит это
  подтверждает — `prompt_style_blocks.py` в диффе отсутствует.
- **Required fix:** убрать F4 из ступени `prompt_style_blocks.py` в архитектурном документе, иначе следующая
  фича контура (F6) унаследует неверную карту эксклюзивов.

### [Severity: Low] L8 — `AntiClicheWorker.start()` без guard владения планировщиком

- **Файл:** `services/anticliche_worker.py:187-204`.
- **Проблема:** в отличие от `lore_worker` (`_owns_scheduler`), при переданном уже запущенном `scheduler`
  вызов `.start()` бросит `SchedulerAlreadyRunningError`. Сейчас `bot.py` планировщик не передаёт, поэтому
  дефект латентный.
- **Required fix:** повторять паттерн `lore_worker`: запускать планировщик только если он не `running`
  (или хранить флаг владения).

### [Info] I1 — Первый недельный тик только через 7 дней после старта

- На свежей таблице кэш пуст первую неделю после деплоя; фича «заводится» лишь после ручного
  `POST /api/anticliche/refresh` или через 7 суток. Не блокер (критерий «воркер по расписанию» выполняется),
  но в runbook T-2135 стоит явно записать ручной прогрев/`next_run_time` при первом старте.

---

## Контракт: чекбоксы

- [x] **Детектор, не scrubber:** динамические правила идут в `find_forbidden_cliches(..., dynamic_rules)` через
  `verbalize_validated`; в промпт не подставляются; `FORBIDDEN_CLICHE_PATTERNS` не подменён; `outgoing_guard.py`
  в диффе отсутствует; `sanitize_outgoing` клише не режет (тесты `TestScrubberDoesNotCutCliches` зелёные).
- [x] **`dynamic_rules=None` байт-в-байт:** `test_dynamic_none_is_byte_equal` + сохранение прежней ветки
  `if not codes and not dynamic_rules`.
- [x] **Вето владельца:** ни `regex`-реза, ни `string.replace` клише; только браковка + ≤2 регенерации
  (`max_retries` capped `_MAX_RETRIES_HARD_CAP`), fallback — лучший вариант.
- [x] **Воркер:** недельный `IntervalTrigger(days=7, jitter=3600)`, `max_instances=1`, `coalesce=True`,
  `misfire_grace_time=3600`; бюджет через `worker_budget.consume`; R17-safe логи (коды/числа/`source`).
  Регистрация/`stop` в `bot.py` (on_startup/on_shutdown), реактивность не нарушена.
- [x] **PG DDL:** `CREATE TABLE IF NOT EXISTS anticliche_cache` + `id` singleton + `CHECK (id=1)`,
  `CREATE INDEX IF NOT EXISTS idx_anticliche_cache_updated`, seed `ON CONFLICT (id) DO NOTHING`;
  SQLite v12 не тронут (Δ SQLite = 0); повторный init — no-op (`test_pg_db` 16×2 зелёный).
- [~] **Фикс S10.22-4b:** базовые кейсы «Он/Она/Оно/Это/Люди/Человек, как …» → `[]`, первое лицо
  «Я, как ИИ…» → `['as_ai']`, «она, как языковая модель» → `[]` — работают. **Остаток: пробел перед запятой (M3).**
- [x] **API RBAC:** GET/POST refresh/PUT — только глобальный админ; 401 без initData, 403 для не-админа,
  422 при >200 входных паттернов, 503 без воркера — тесты зелёные; фразы не логируются (в логи идут count/version/source).
- [x] **`EXTRACT_SYSTEM_PROMPT`** не перечисляет клише (контент), но тест-гаранта нет (**L6**).
- [x] **Инварианты:** физический two-call пайплайн не изменён; egress-реестр не расширялся (новых send-точек нет);
  R16-аддитивно; R17/R18 — секретов и сырого текста в логах нет; Δ каталога = 0; порядок роутеров `bot.py`
  не сдвинут (добавлены только импорт/старт/стоп, роутер — в `web/app.py`, путём без коллизий).
- [~] **Тесты:** покрытие широкое (разбор/дедуп/лимит/детектор/scrubber/ретраи/S10.22-4b/fail-open/DDL/API),
  но есть пробелы: M1 (пустой результат), M2 (генератор), M3 (пробел+запятая), L6 (промпт-гарант).

## Δ каталога / БД

- **Δ каталога = 0** — `DYNAMIC_ANTICLICHE_ENABLED` — env-only `ClassVar`, `ANTICLICHE_MAX_PATTERNS` —
  код-константа; `test_param_catalog` зелёный.
- **Δ SQLite DDL = 0** (v12); единственное DDL — PG-таблица `anticliche_cache` + индекс + seed.
- PG: JSONB-кодеки (`pg_db._init_connection`) совместимы с записью Python-списка и чтением списка — подтверждено.

## Итог

Critical: 0. High: 1 (H1). Medium: 2 (M2, M3). Low: 8 (L1–L8). Info: 1 (I1).
Ядро соответствует ADR-1023-4, но фича не может считаться принятой, пока H1/M2/M3 не закрыты.
**Возврат @Builder.** Отчёт для @PM/@Architect: архитектурный документ требует синхронизации (L7).

---

# Итерация 2 — коммит `4e05579` (повторный аудит)

- **`4e05579^ == 67278f2`** (поверх ветки лежит F5 `67278f2`; его правки F4 **не приписаны**).
- **Диф итерации строго F4:** `git diff 4e05579^ 4e05579 --name-only` → только
  `services/anticliche_cache.py`, `services/anticliche_worker.py`, `services/negative_constraints.py`,
  `web/api/anticliche.py`, `tests/test_anticliche_round1023.py`. `outgoing_guard.py` / `prompt_style_blocks.py`
  / `pg_db.py` / `bot.py` / `config/settings.py` / `param_catalog.py` / `telegram_send.py` — **вне диффа**.

## Статус: APPROVED

Все замечания итерации 1 закрыты по существу, новых блокеров нет. Проверено не по словам, а запуском.

## Закрытие замечаний итерации 1

- **[H1] Пустая/вырожденная выборка больше не затирает кэш.** `services/anticliche_worker.py:292-301`:
  `if not patterns:` → `fetch_cache` (для версии), `mark_status(pg, "empty")`, возврат `status="empty"`;
  `write_patterns` не вызывается. Проверено: непустой кэш (v5) + LLM `{"patterns": []}` → `{'status':'empty','count':0,'version':5}`,
  `patterns` = `[{'code':'dyn_keep',...}]`, `version` = 5, `last_status` = `empty`.
  Эхо хардкода (`подводя итог`/`надеюсь, помог`) → тот же результат. Пустая запись — только через явный `apply_manual` (ручной `PUT`).
- **[M2] Итератор `dynamic_rules` материализуется один раз.** `negative_constraints.py:311` (`dyn = tuple(...)`)
  и `:381` в `verbalize_validated`; ретраи используют `dyn`. Проверено: генератор из одного правила →
  `calls=3, retries=2, hits=['dyn_e780066d'], fallback=True` — клише находится повторно, не исчерпывается.
- **[M3] Пробел перед запятой.** Добавлены `(?<!\bон\s,\s)` и аналоги (7 местоимений × 3 варианта).
  Проверено: `"Он , как искусственный интеллект…"`, `"Люди , как ИИ"`, `"Оно , как языковая модель"` → `[]`;
  первое лицо сохранено: `"Я, как ИИ, отвечаю"`, `"я как искусственный интеллект"`, `"как языковая модель отвечаю"` → `['as_ai']`.
  Новых ложных отрицаний от добавленных lookbehind нет (они только подавляют третьеличные сравнения).
- **[L1]** `_ALLOWED_STATUSES` удалена из воркера, `ALLOWED_STATUSES` + `_safe_status` в
  `anticliche_cache.py:28-31,178-181` (unknown → `never`). Проверено: `bogus_status` → `never`, `empty` → `empty`.
- **[L2]** `apply_manual` вынесен в модульную функцию `anticliche_worker.py:327-338`; `PUT /api/anticliche`
  (`web/api/anticliche.py:120-129`) ходит через неё — единый путь бизнес-логики, дубль удалён.
- **[L3]** `fetched_at` через `COALESCE($5::timestamptz, …)` (`anticliche_cache.py:39-48`); `_STATUS_SQL`
  (`:53`) больше не двигает `updated_at`. Проверено: ручная правка сохраняет `2026-01-01T00:00:00+00:00`.
- **[L4]** `PatternIn.phrase/origin` получили `max_length=500/200` (`web/api/anticliche.py:33-36`);
  тест `test_put_422_phrase_too_long` (501 символ → 422).
- **[L5]** Бюджет: `fetch` → проверка `METRIC_CALLS` → LLM → `METRIC_TOKENS` сразу после ответа,
  независимо от исхода парсинга (`anticliche_worker.py:245-283`). Учёт call/tokens корректен.
- **[L6]** `TestPromptInvariants` (`tests/test_anticliche_round1023.py`): `EXTRACT_SYSTEM_PROMPT` не цитирует
  тропы; ни одно сообщение, переданное в `generate_call`, не содержит фразы динамического правила.
- **[L7]** `round1023-architecture.md` синхронизирован: строка 34/198 (F4 — канон no-op) и 202
  (`prompt_style_blocks.py` → ступень **только F3**). Противоречие с ADR-1023-4 снято.
- **[L8]** `start()` не перезапускает уже работающий внешний планировщик (`anticliche_worker.py:199-201`);
  тест `test_start_does_not_restart_running_scheduler`.

## Инварианты (повторно)

- **Детектор, не scrubber:** ✅ — `outgoing_guard.py` вне диффа, клише по-прежнему только бракуются/регенерируются.
- **`FORBIDDEN_CLICHE_PATTERNS` цел:** ✅ — изменено только тело ветки `as_ai` (добавлены lookbehind), сам список не подменён.
- **Промпт не тронут:** ✅ — `prompt_style_blocks.py` и каноны вне диффа; `test_de_robotization_round1021` зелёный.
- **Egress:** ✅ — новых send-точек нет.
- **R16/R17/R18:** ✅ — секретов/сырого текста в логах нет; API-ответы не логируются.
- **Δ каталога = 0:** ✅ — `config/settings.py`/`param_catalog.py` вне диффа; `test_param_catalog` зелёный.
- **Порядок роутеров `bot.py`:** ✅ — `bot.py` вне диффа итерации.

## Тесты

- Целевой `tests/test_anticliche_round1023.py` — **76 passed**.
- Батч `anticliche + negative_constraints_round1022 + pg_db + param_catalog + de_robotization_round1021 +
  outgoing_guard_round1022 + webapp_round1012_ui` — **269 passed**.
- **Полный pytest (локально, на дереве с F5):** **7248 passed / 1 failed** (96.7 с).
  Единственный провал — `tests/test_image_generation_round1023.py::TestGetMode::test_get_url_and_no_key_leak`
  (**это F5 `67278f2`, не F4**): тест ждёт API-ключ в GET-URL. F4 к нему отношения не имеет.
- Прогон №1 полной сюиты дал дополнительный провал
  `tests/test_settings_worker_sync_round1018.py::TestListenerFailOpen::test_no_pool_returns_none_with_warning`
  (import `bot.py`), прогон №2 — прошёл; в изоляции и в паре с F4-файлом — **107 passed**.
  Это пре-существующая order/timing-флак-теста (reload `config.settings` + import `bot`), к F4 не относится.
- Заявленные автором 7249/0 локально не воспроизводятся из-за F5-дефекта; **гейт F4 при этом чист**.

## Advisory (не блокирует)

- **A1 (Info).** Крайний вариант M3: `"Он ,как ИИ"` (пробел перед запятой, но **без** пробела после) всё ещё
  даёт `['as_ai']` — `(?<!\bон\s,\s)` требует пробел после запятой. Вариант с отсутствующим пробелом после запятой
  не входит в формулировку S10.22-4b и крайне редок; если захочется добить — добавить fixed-width
  `(?<!\bон\s,)` (без завершающего `\s`). Не блокер.
- **A2 (Info).** L5-перестановка: при исчерпанном бюджете источник всё равно скачивается (fetch до проверки
  `METRIC_CALLS`) — осознанный размен ради корректного учёта; недельный HTTP-GET пренебрежимо дёшев.

</content>
