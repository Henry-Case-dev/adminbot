# FCT-S8-EVIDENCE — одиночный сбой admission-теста (28.11.2026)

Диагностика Builder. Продукт не менялся: правка только в тесте.
База: `c3c0e1cb3` (продукт `f6cd011e0`), ветка
`fix/fct-insufficient-evidence-title-2026-11-28`.

## 1. Классификация: **(б) устаревшее ожидание теста**

Не продуктовый дефект. Публикуемый текст `Проверка не завершена: поиск
недоступен` в этом прогоне — требуемое поведение S4/владельца, а не регрессия.

### Наблюдённая цепочка

1. `tests/test_evol_fc_admission.py::TestScenario7InsufficientEvidence`
   собирает `service = MagicMock()`; `service.aggregator` поэтому —
   автоматический `MagicMock`, а не «поиска нет».
2. До `f6cd011e0` заводское `FACTCHECK_PIPELINE_V2_ENABLED=False`, планировщик
   не строил план, retrieval не выполнялся, вердикт рендерился из замоканного
   `check_claim_envelope` → заголовок «Недостаточно данных для проверки».
3. `f6cd011e0` (FCT-S6 U3) переводит заводское значение
   `FACTCHECK_PIPELINE_V2_ENABLED` в `True` (правило проекта 09.11.2026).
   В том же коммите legacy-тесты закреплены явно
   (`tests/test_factcheck_handlers.py`: autouse-фикстура `_pipeline_v2_enabled
   -> False`), а `test_evol_fc_admission.py` не закреплён.
4. С v2 ON тест реально проходит retrieval: план строится, двойник
   `aggregator` даёт `provider_error` (в офлайн-тесте нет провайдеров) →
   `derive_execution_state` = `technical_unverified`, `execution_cause=
   provider_error`; `factual_verdict` остаётся `insufficient_evidence`.
5. `factcheck_renderer._content` при `technical_unverified` ставит технический
   заголовок (`FCT-603`, S4 U3) — «поиск недоступен». Тело вердикта не
   меняется. Отсюда падение старого `assert "недостаточно данных" in sent`.

## 2. Что видит человек (фактические строки)

Двойник сценария, одинаковые входы, различается только фактическое состояние
retrieval (raw: `raw/user-visible-texts.txt`):

| Состояние прогона | Публикуемый текст (Telegram HTML) |
|---|---|
| A. Провайдеры недоступны (`provider_error`, `technical_unverified`) | `<b>Проверка не завершена: поиск недоступен</b>\n\nПроверил доступные материалы: проверяемых ссылок, подтверждающих заражение через стикер, не нашёл.` |
| B. Поиск выполнен, релевантных источников нет (содержательный `insufficient_evidence`, `complete`) | `<b>Недостаточно данных для проверки</b>\n\nПроверил доступные материалы: проверяемых ссылок, подтверждающих заражение через стикер, не нашёл.` |

В обоих случаях это не `no_claim`-фраза. Технический заголовок — человеческая
формула без внутренних кодов (`ev-N`, `status_detail`, провайдеры не утекают).

## 3. Проверка контракта публикации

- `s4-design.md` §4/U3 (FCT-602/603): «технический заголовок не равен
  „Недостаточно данных“»; негативный контроль — мутация «technical →
  `_VERDICT_HEADLINE[insufficient]`» → RED. `decisions.md` D3: техническое
  состояние — отдельная ось (`CheckedVerdict.execution_status`), вердикт не
  подменяется.
- `plans/current_task.md` §11.2 п.1/п.7, §11.3: технический сбой поиска
  называется техническим исходом; «не переводить все проблемы в одинаковое
  „Недостаточно данных“»; заголовок и комментарий согласованы.
- Acceptance-строки: `FCT-150` = сценарий §5.1 (forward + календарь Миронова),
  `FCT-176` = сценарий §5.27 (сохранённый отправленный текст; ссылки ⊆
  EvidenceMap; без OCR/JSON/technical протечки). Ни одна не требует фразы
  «недостаточно данных» именно в случае сбоя поиска; технической протечки нет.
- Независимое покрытие обеих веток уже существует:
  `tests/test_factcheck_post_release_w1.py::test_no_confirmation_is_not_technical_failure`
  (complete → «недостаточно данных», без «проверка не завершена») и
  `::test_technical_failure_keeps_honest_headline` (technical → технический
  заголовок); плюс `tests/test_fc_trust_render.py`.

Вывод: публикация S4-контракт не нарушает; ошибочно было ожидание теста,
которое держалось на заводском OFF рубильника v2.

## 4. Правка (только тест)

`tests/test_evol_fc_admission.py`:

- добавлен локальный двойник `_no_relevant_evidence_retrieval()` — сценарий
  §5.7 «поиск выполнен, релевантных источников нет» (содержательный
  `insufficient_evidence`, `no_relevant_sources`, не технический);
- в тесте §7 подменяется `fsp.run_retrieval`, чтобы офлайн-двойник
  `service.aggregator` не изображал сбой провайдера;
- assert «недостаточно данных» сохранён; добавлен отрицательный
  `assert "проверка не завершена" not in sent.lower()` — технический сбой не
  может выдаваться за отсутствие данных (дискриминирующий контроль: ветка A
  этого теста не проходит).

Ослабления нет: сценарий по-прежнему требует содержательного
insufficient-ответа, не из пула `no_claim`; добавлена защита от подмены
техническим заголовком.

## 5. Прогоны (фактические команды)

| Проверка | Результат | Артефакт |
|---|---|---|
| RED: исходный тест на `c3c0e1cb3` | `1 failed` (assert «недостаточно данных»; фактический текст — технический заголовок) | `raw/red-baseline-c3c0e1cb3.txt` |
| GREEN: исправленный §7 | `1 passed` | `raw/green-scenario7-fixed.txt` |
| GREEN: весь `tests/test_evol_fc_admission.py` | `22 passed` | `raw/green-admission-file.txt` |
| GREEN: смежные фактчек-наборы (`test_fc_trust_verdict`, `test_fc_trust_render`, `test_factcheck_post_release_w1`, `test_factcheck_handlers`, `test_factcheck_planner_cfg06`) | `158 passed` (1 pre-existing warning: leaked aiosqlite connection) | `raw/green-related-factcheck-suites.txt` |
| Пользовательские тексты A/B | см. §2 | `raw/user-visible-texts.txt` |

Команды: `python -m pytest <файл>::<класс> -q`, затем файл целиком и смежный
набор; cwd — рабочий worktree ветки.

## 6. Попутная находка (важно для приёмки S7)

`f6cd011e0` — **не** «выложенный `3a78484b9` + только aggregate endpoint».
В нём также:

- `config/settings.py`: `FACTCHECK_PIPELINE_V2_ENABLED` заводское
  `False → True` (и docstring `pipeline_v2_enabled`);
- правки трёх legacy-тестов под новое заводское значение
  (`test_factcheck_handlers.py`, `test_factcheck_planner_cfg06.py`,
  `test_round1025_f8_registry`/`test_mca20_integration_round1045`/media-тест).

То есть S7-харнесс на этой базе исполняет **v2-путь**, тогда как выложенный
`3a78484b9` (2.58.271) имел заводское OFF. Для приёмки S7 это нужно отразить в
записи effective-конфигурации (S4-D6), иначе «проверено на кандидате» и
«проверено в проде» относятся к разным контурам.

## 7. Продуктовый фикс

Не требуется. Продуктовый код не изменялся; локальная правка — только тест.

## 8. Ограничения

- Проверка детерминированная, офлайн: живые провайдеры и фактическая отправка
  в Telegram не проверялись (это вне предмета задачи).
- Фраза «недостаточно данных» для содержательного insufficient-прогона
  проверяется на уровне оркестратора этим тестом и независимо — на уровне
  сервиса (`test_factcheck_post_release_w1.py`).

## 9. sha256 артефактов

См. `SHA256SUMS` (raw-файлы и этот документ проверяются `sha256sum -c`).
