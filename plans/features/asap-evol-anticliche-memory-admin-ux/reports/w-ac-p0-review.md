# Ревью W-AC-P0: AntiCliche больше не стимулирует перегенерацию

- Пакет: AC-P0; ветка feat/ac-p0-no-retry
- Проверенный кандидат: код acb8cfe4, документация 031af697, база f1219a14
- Независимое ревью: чтение кода, собственные пробы, мутации, прогон на базе
- Вердикт: Needs Fixes, и только из-за состояния карты и строгого гейта, не из-за кода

## 1. Существо вердикта

Поведение соответствует ТЗ владельца (FINAL v8, инварианты 1 и 2; ADR п.3): стилевое попадание больше не перегенерирует ответ, независимые guard-ы сохранены со своими причинами, стиль нигде не замаскирован под format/metatext.

Код и тесты пакета к приёмке готовы. Единственная причина, по которой нельзя выдать Approved, это карта требований:

- FAIL: candidate mismatch, в карте пуст candidate_commit;
- FAIL: все 20 строк AC-P0 в статусе PENDING, evidence пуст;
- итог гейта: stage=review inventory=521 scoped=23 errors=24.

Это работа PM: проставить candidate_commit, привязать доказательства, затем статусы. Строки-инвентаризации (AC-BASELINE-FACTS, AC-STEP1-INTEGRATE-HEAD, GLOBAL-3-HEAD-BASELINE) к этому кандидату не относятся и закрываться им не должны.

## 2. Что проверено в коде (Implementation)

Путь исполнения verbalize_validated в services/negative_constraints.py:

- split_rule_codes() - единственное место разделения: 9 кодов правил = 7 STYLE_SIGNALS + 2 FORMAT_GUARDS, пересечений нет, неклассифицированных нет (проверено импортом модуля, не чтением глазами).
- Цикл повторов: приоритет metatext, form, numeric, format; ветка else теперь break; стилевые коды в выборе причины повтора не участвуют.
- Ранжирование лучшего кандидата: (metatext_ok, form_ok, numeric_ok, format_ok), вес числа клише (-len(codes)) убран.
- anti_cliche_retries и cliche_observed лежат в стартовом stats, поэтому присутствуют на всех путях, включая kill-switch и ошибку повтора.
- retry.cliche остаётся только дескриптором в prompt_registry (каталог W3); рантайм его в промпт не резолвит. Недостижимость подтверждена AST-тестом и grep по всему коду.

Вызывающие (direct_chat_service, factcheck_service, summary_generator) передают channel_enabled_rules("plain", mode), то есть форматный guard plain_no_tables включён в проде, а не является мёртвым кодом. Побочный эффект factcheck_service.py:1649 (отбрасывание при fallback) стилевой ответ больше не отбрасывает, как и требует инвариант 1.

Новых prompt-текстов нет: FORMAT_NO_LISTS_RETRY_TEXT собран из существующих ANTI_BOT_HEADER + ANTI_BOT_ITEMS[3] (пункт 4 про перечни), то есть реестр фабричных текстов не менялся.

## 3. Матрица вызовов модели (мои пробы, не пробы Builder)

Канал plain, max_retries=2, ответы задаются детерминированно.

| Сценарий | Вызовов | retries | анти-клише | промпт повтора |
|---|---|---|---|---|
| только стиль (as_ai + hope_helped), plain-правила | 1 | 0 | 0 | нет |
| только динамическое dyn_* правило | 1 | 0 | 0 | нет |
| неизвестный код правила | 1 | 0 | 0 | нет |
| стиль + numeric mismatch | 2 | 1 | 0 | NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT |
| стиль + numeric, max_retries=99, numeric неисправим | 2 | 1 | 0 | numeric, потолок держится |
| формат: таблицы | 2 | 1 | 0 | FORMAT_PLAIN_TEXT_BLOCK |
| формат: перечни | 2 | 1 | 0 | FORMAT_NO_LISTS_RETRY_TEXT |
| form guard | 2 | 1 | 0 | FORM_GUARD_RETRY_SYSTEM_PROMPT |
| metatext + стиль + таблица | 2 | 1 | 0 | METATEXT_RETRY_SYSTEM_PROMPT (приоритет) |
| ошибка генерации на повторе (стиль + таблица) | 2 | 0 | 0 | format; fallback и retry_error выставлены |
| таблица, затем только стиль | 2 | 1 | 0 | format; вернулся текст второго ответа |
| стиль, все guard-ы включены, нарушений нет | 1 | 0 | 0 | нет |
| kill-switch OFF | 1 | 0 | 0 | нет |

Во всех строках стилевой промпт не отправлялся ни разу, ни одна строка не превысила жёсткий потолок в 3 генерации.

Ранжирование, отдельная проба с моим входом: кандидат 1 это три клише плюс таблица, кандидат 2 без клише плюс таблица. На кандидате 2 вызова и возвращён кандидат 1, то есть стиль на выбор не влияет. На базе f1219a14 три вызова и возвращён кандидат 2, то есть стиль решал. Разница ровно в снятии веса клише.

## 4. Матрица guard-ов (причины не подменены)

| Guard | Ключ причины | Значение | Свой промпт |
|---|---|---|---|
| формат таблиц | format_guard_reason | format_retry | FORMAT_PLAIN_TEXT_BLOCK |
| формат перечней | format_guard_reason | format_retry | FORMAT_NO_LISTS_RETRY_TEXT |
| форма G1-G3 | form_guard_reason | form_guard_rejected | FORM_GUARD_RETRY_SYSTEM_PROMPT |
| числовые утверждения | numeric_claim_reason | numeric_claim_corrected | NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT |
| метатекст | metatext_reason_code | код причины | METATEXT_RETRY_SYSTEM_PROMPT |
| стиль | cliche_observed и hits | коды | повтора нет |

Стилевой ответ не порождает ни одного ключа format_*, form_*, metatext_*, numeric_*. Обратной подмены (формат, переименованный в стиль) тоже нет.

## 5. Качество тестов (Test validity)

- TestAntiClicheNeverRegenerates: gen.await_count == 1, неизменность текста, retries == 0, коды в cliche_observed и hits, отсутствие стилевого промпта в отправленных сообщениях.
- TestIndependentGuardsStillFire: точное сравнение промпта повтора с константой, счётчики причин, format_fallback при исчерпании, потолок в 3 генерации.
- test_clean_first_attempt_single_call: сравнение словаря stats целиком, поэтому появление или исчезновение любого ключа ломает тест.
- test_cliche_retry_prompt_unreachable: настоящий AST-обход (ImportFrom-алиасы, все Name и Attribute, hasattr). Проверен мутацией ниже.

## 6. Мои мутации (все три красные, файл восстановлен байт-в-байт)

| Мутация | Результат |
|---|---|
| as_ai возвращён в FORMAT_GUARDS (стилевой повтор вернулся) | 10 падений, включая test_style_signal_single_generate_call[as_ai], test_multiple_style_hits_single_call, test_style_never_sends_retry_prompt, test_style_hit_is_not_reported_as_guard, test_style_plus_numeric, test_style_plus_format |
| FORMAT_RETRY_REASON = form_guard_rejected (маскировка формата) | 5 падений, включая оба format-теста и test_style_plus_format_uses_format_reason |
| возвращён импорт CLICHE_RETRY_SYSTEM_PROMPT | 2 падения, включая test_cliche_retry_prompt_unreachable |

После отката git status пуст, файл совпадает с кандидатом побайтово.

## 7. Прогоны на кандидате и на базе

Целевые наборы (test_negative_constraints_round1022, test_mca08_style_form, test_anticliche_round1023, три *_two_call_round1022): 255 passed, 2 failed.

Все 4 падения, названные Builder, воспроизведены на базе f1219a14 в том же venv, поэтому это не регрессии AC-P0:

| Тест | Кандидат | База f1219a14 |
|---|---|---|
| test_mca08::TestObservabilityRegistry::test_declared_events_really_emitted_in_code | FAIL | FAIL |
| test_summary_two_call_round1022::TestSummaryTwoCall::test_editor_then_narrator | FAIL | FAIL |
| test_verbilizer_response_modes_round1023::TestTwoCallModes::test_summary_kill_switch_off_prev_narrator | FAIL | FAIL |
| test_outgoing_guard_round1022::TestSendPointsCoverage::test_every_send_point_is_registered_or_allowlisted | FAIL | FAIL |

Реестровая выборка (-k "registry or factory_text or soul_amd or canon"): кандидат 929 passed и 5 failed, база 928 passed и 5 failed, набор падений идентичен. В частности test_asap8_v6_p1_d11_registry::test_env_off_beats_product_toggle падает только при совместном запуске и на базе тоже, это изоляция тестов, не код.

## 8. Коллатеральные правки тестов: суждение

Все пять файлов пересчитаны под новый контракт, ослабления проверок не нашёл:

- test_anticliche_round1023.py: динамические правила переведены с 3 вызовов и 2 повторов на 1 вызов, добавлены anti_cliche_retries и cliche_observed.
- test_mca08_style_form.py: точные словари stats дополнены двумя ключами, стилевой кейс перевёрнут на «повтора нет» с проверкой отсутствия стилевого промпта.
- три *_two_call_round1022.py: триггер повтора заменён со стиля на форматный guard, число вызовов пересчитано (3, 3, 4 и 3), интеграционный механизм (реальный сервис и реальный цикл) сохранён.

Одна потеря покрытия, не блокирует (см. п.9.2): test_generator_rules_survive_retries стал test_generator_rules_survive_single_call с одним вызовом, из-за чего исходная опасность M2 (исчерпание генератора правил именно на повторе) тестом больше не воспроизводится. Само поведение я проверил пробой: генератор правил плюс форматный повтор дают 2 вызова, исключения нет.

## 9. Некритичные замечания (этот пакет не блокируют)

9.1. Телеметрия формата при чужом повторе. Если ответ нарушает и метатекст, и формат, повтор идёт по метатексту, но format_rejects=1 и format_guard_reason=format_retry уже проставлены (флаг format_retry остаётся False). На вызовы и текст не влияет, но пакет AC-API не должен трактовать format_guard_reason как «повтор был». Минимальная правка на будущее: выставлять format_guard_reason только в ветке фактического повтора.

9.2. Покрытие M2 (см. п.8): стоит вернуть сценарий с генератором правил на форматном повторе, это одна строка в существующем тесте.

9.3. retry.cliche в реестре промптов остаётся видимым описанием с устаревшими якорями (negative_constraints.py:813). Рантайм его не использует; скрытие или перемаркировка это задача AC-UI и AC-API, а не AC-P0, так как удаление изменило бы набор фабричных текстов и байт-пины SOUL-AMD.3.2.

## 10. Что этим ревью не доказано

Реальный ответ модели и отсутствие клише в живом тексте это предмет пакета подсказок, не AC-P0. Деплой в этом пакете запрещён, живой чат не проверялся.

## 11. Приёмка по строкам (поведенческие строки AC-P0)

| Строка | Статус ревью | Доказательство |
|---|---|---|
| AC-INV-01 | VERIFIED | матрица п.3, 1 вызов на стиль; мутация A |
| AC-INV-02 | VERIFIED | матрица guard-ов п.4; стиль не порождает guard-ключей |
| AC-MET-RETRIES-ZERO | VERIFIED | anti_cliche_retries == 0 во всех 13 строках п.3 |
| AC-DOD-ZERO-RETRY | VERIFIED | п.3 и п.4 целиком |
| T-PR-NO-RETRY | VERIFIED | 7 стилевых кодов, множественные попадания, dyn_* дают 1 вызов |
| T-PR-NUMERIC | VERIFIED | стиль плюс numeric: 2 вызова, только numeric-повтор; ранжирование без веса клише |
| T-PR-FORM | VERIFIED | format, form, metatext со своими причинами и текстами |
| T-PR-NO-CLICHE-PROMPT | VERIFIED | AST-тест плюс мутация C, стилевой промпт не отправлен ни разу |
| AC-BAN-RETRY-PATHS | VERIFIED | ветка else: break, в модуле нет стилевого retry-пути |
| GLOBAL-7-NO-STYLE-MEMORY-RETRY | VERIFIED | стиль не выдан за form, format или metatext |
| AC-STEP2-P0-REPAIR | VERIFIED для retry и ranking | п.3; сетевые и source-части относятся к AC-DATA |
| AC-BASELINE-FACTS, AC-STEP1-INTEGRATE-HEAD, GLOBAL-3-HEAD-BASELINE, AC-INV-04 | вне этого кандидата | строки инвентаризации, закрываются другими пакетами |

## 12. Следующее действие

1. PM: проставить candidate_commit=acb8cfe4, привязать доказательства (этот отчёт, отчёт Builder, имена тестов), закрыть поведенческие строки AC-P0 и повторить --stage review. Строки инвентаризации этим кандидатом не закрывать.
2. Builder: обязательных правок нет. Пункты 9.1 и 9.2 по желанию, одной малой правкой, без нового ревью пакета.
