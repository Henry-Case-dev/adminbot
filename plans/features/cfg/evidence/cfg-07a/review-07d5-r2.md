# Review REV-07D5-R2 — повторное ревью ремонта F1–F4 (волна 07D.5)

- **Вердикт: Approved** (0 блокирующих; все 4 находки review-07d5 закрыты).
- **Кандидат:** uncommitted worktree поверх HEAD `ce77b2c4` (прод 2.58.103).
  Коммитов/пушей/деплоя/чатов нет; биндинг за оркестратором. Read-only ревью:
  живые отправки не выполнялись, внешние вызовы — только локальные pytest/пробы.

## Проверка находок (все независимо воспроизведены 21.10.2026)

**F1 — закрыт.** `test_kill_switch_bypasses_metatext` патчит КЛАСС
(`monkeypatch.setattr(type(settings), "SYSTEM2_VALIDATOR_LOOP_ENABLED", False)`,
тест-файл :432) + ассерт тени `... not in vars(settings)` (:442). Флаг —
`ClassVar[bool]` (config/settings.py:553), фикс адресует механику точно.
Проба-репро дефекта: старый инстанс-паттерн оставляет тень
(`in vars`=True), класс-патч False перекрывается (чтение=True) — именно тот
RED (3 вызова vs 1). Grep по tests/: писателей инстанса флага нет — conftest
(:104) и nc1022 (:151) патчат только классы, ассерт vars устойчив в композитных
прогонах. Речек: комбо new+nc1022 → **74 passed, EXIT 0** (до ремонта 1 failed).

**F2 — закрыт.** `test_bracket_strip_keeps_honest_brackets` (:158–170),
`TEST-LIFECYCLE: REGRESSION owner=CFG-07D5 (review-07d5 F2)`: `[1]` и
`[прим. автора]` целы, FA-08 срезается (и `strip_guard_findings`, и
`guard_public_text`, repaired=True). Код `_bracket_block_re` не менялся:
`re.escape(head[1:])` — тело экранируется без ведущей `[` (форма, верифицированная
в раунде 1); регрессия дефектной char-class-формы теперь поймана тестом.

**F3 — закрыт.** `_SEM_VERIFY_VERB_RE` — негативные lookbehind фиксированной
ширины `(?<!\bне\s)(?<!\bне\s\s)` + `\b`-якорь (переменная длина в `re`
запрещена — два паттерна корректны). Пробы: честное «Тезис не подтверждён —
весь интернет я не проверил.» → find=() / retry=None; двойной пробел → ();
начало предложения («Не проверил я весь интернет.») → (); «Вся сеть была
изучена мной вчера» → детект (`semantic:total_verification_variant`); грязная
инверсия → retry-код прежний. `_INVERSE_STRIP_RE` не задет (использует сырой
`_SEM_VERIFY_VERB_BODY` без lookbehind); честная негация на delivery-шве —
байт-паритет, findings=() (проба; «не» не в списке местоимений strip-грамматики).
REGRESSION-тест `test_honest_negation_not_flagged_dirty_inverse_is` (:243).

**F4 — закрыт.** Комментарий в `guard_public_text` теперь гласит: телеметрия
+ срез defense-in-depth (`_INVERSE_STRIP_RE` в `_strip_matches`) — по факту
кода. Тест переименован в `test_apply_guard_semantic_reports_and_strips_inverse`
(:626), докстринг и ассерты фактические (changed/repaired=True, инверсия
срезана, «Тезис подтверждается» цел). Проба шва: dirty → findings semantic,
changed/repaired=True, text='Тезис подтверждается. .' (остаток « .» —
существующий класс уборки, вне скоупа, задокументирован). 07d5-summary.md §2.2
исправлен с пометкой о неверной первичной формулировке. sha карты обновлён:
`artifact_sha256` = f8c7baa010f1982e9605adadf63267dd2d6eef7698bb288690b1fcb054fcb98c
== фактический sha256(07d5-summary.md); JSON валиден; статус L00380 PENDING;
observation-строка не тронута (числа 39/232 до ремонта сохранены по
DO_NOT_TOUCH — актуальные 41/234/74 в пиннутом summary §4).

## Прогоны (независимые, 21.10.2026)

| Набор | Результат |
|---|---|
| `tests/test_cfg07_guard_07d5.py` | **41 passed, EXIT 0** |
| F1-комбо new + nc1022 | **74 passed, EXIT 0** |
| Сводный фокус (new+egress_dictionary+guard_tail+route_coverage+anticliche) | **234 passed, EXIT 0** |
| Валидаторная семья: mca08_form+nc1022+mca15+tool_router | **252 passed, EXIT 0** |
| anticliche_round1023 (отдельная сессия) | **79 passed, EXIT 0** |
| POSITIVE-проба пулов smartmodule_phrases (детекторы + байт-паритет guard) | **202 checked, 0 bad** |
| Пробы F3/F4 (python, реальный guard) | все по контракту (см. выше) |

## Гигиена

numstat vs `ce77b2c4`: public_speech_guard 243+/5- (прирост +8 к раунду 1 =
F3-lookbehind + F4-комментарий), negative_constraints 78+/8-, factcheck_service
23+/2-, prompt_style_blocks 14+/0- (три последних — без изменений к раунду 1),
карта cfg — один ханк (строка L00380), тест-файл новый (41 тест = 39+2).
mtimes: R2-правки 08:09–08:14 ровно по 4 файлам лейна (guard/тест/summary/карта);
остальные грязные файлы worktree (mca-17c, asap8, samples-ux, owner_*,
w7-dispute-metrics 08:00) — чужие лейны, вне скоупа этого ремонта.

## Попутное (nonblocking, не блокирует)

- Тройной+ пробел между «не» и глаголом не покрыт lookbehind → теоретический
  ложный триггер на вырожденном вводе; последствие ограничено (≤1 retry,
  fail-soft, текст не режется). Дегенеративный кейс; фикс тривиален при
  случае, отдельно не требуется.
- Прецедент HEAD (закрытый сет 07D.2 слеп к негации: «Я не проверил весь
  интернет» → closed-hit → срез на шве) — вне волны, корпусной ремонт 07A.7
  (унаследовано из review-07d5 без изменений).

## Биндинг

Кандидат: uncommitted worktree @ HEAD ce77b2c4; коммит и ledger-переключение —
оркестратор (статус строки PENDING не менялся этим лейном). Evidence:
07d5-summary.md (sha256 f8c7baa0…), 07d5-tests.txt, review-07d5.md (раунд 1),
этот файл.
