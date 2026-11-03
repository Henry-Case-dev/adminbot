# PVR-S5 (постоянный стандарт) + PVR-S6 (аудит принуждения) — независимое ревью

**Кандидат:** ветка `pv/std`, коммит `4b4d1160`, база `4baccb1d`.
Диф: 7 файлов, +916/−55 — контракт, `AGENTS.md`, `README.md`, тест аудита, evidence `pvr-s6`.
Продуктовый код (`services/`, `web/`, `config/`, `scripts/`, `bot.py`) не тронут, DDL нет.

**Вердикт: Needs Fixes** — две фактические неточности в самом документе (§5 «фактический прогон» и §8 п.5 про `partial_save`).
Всё остальное принято: правило, дрейфы 1–4 и 6–8, аудит и его падучесть, байты и отсутствие изменений продукта — доказано.
Правка чисто документальная (одна строка в §5, 2–3 строки в §8 п.5), затем фокусная перепроверка; полный прогон эпика не нужен.

## 1. По пунктам задания

| # | Пункт | Статус | Доказательство |
|---|---|---|---|
| 1 | Правило совпадает с волей владельца и размещено там, где его читают | PROVEN | Цитата §1 контракта после нормализации markdown идентична формулировке владельца (387 символов, сравнение строк). Размещено в `AGENTS.md` (абзац «Блокер релиза», авточитаемые инструкции агентов) и в `docs/prompt-versioning-contract.md` §1. Запрет менять сегодняшние тексты мемов объявлен ограничением только этого пакета; глобального запрета в `AGENTS.md`/`README.md` нет |
| 2 | Восемь дрейфов исправлены против кода | PROVEN по 7 из 8, NOT PROVEN по цифрам grep-аудита (F1) | см. §3 |
| 3 | Аудит умеет падать и не вакуумный | PROVEN | три мутации Builder-а и две мои независимые — все CAUGHT; тест импортирует реальные `prompt_registry`, `param_catalog`, `prompt_release_policy`, `create_app`; счётчики 112/111/102/39/73 запинены |
| 4 | Открытые пункты честны, с владельцами, включая новый | PROVEN по составу и новому пункту; NOT PROVEN по §8 п.5 (F2) | 6 пунктов с владельцами PVR-S6-AUDIT / PVR-S1-WRITE; новый пункт про «неправильную форму» `character.core` точен (код `prompt_release_policy.py:829-834`); строка runbook про `--force` есть в `README.md` и в §8 п.3 |
| 5 | Нет изменения продуктового поведения | PROVEN | diff по `services/ web/ config/ scripts/ bot.py` пуст; DDL в диффе нет; байты мемов: joke 95 байт `2f30ca1f9a6b`, image 51 байт `f81fe7e4b505`, идентичны снимку PVR-S1; `FACTORY_SET_SHA256_12 = e9dc109330a8`, реестр не менялся |

## 2. Прогоны

| Набор | Факт | В отчёте Builder-а |
|---|---|---|
| `test_prompt_field_audit.py` | 15 passed | 15 passed |
| + `test_evol018_prompt_audit`, `test_prompt_versioning_enforcement`, `test_evol012_barrier_retired` | 60 passed | 60 passed |
| `test_prompt_baseline`, `test_prompt_history_pagination`, `test_evol016_prompt_activation`, `test_evol017_prompt_history_ui` | 77 passed, 1 skipped | 77 passed, 1 skipped |
| `test_evol016_prompt_journal_v39`, `test_prompt_migrations`, `test_summary_asap21_prompt_migrations`, `test_asap_prompt_history_integrity` | 78 passed, 1 skipped | 78 passed, 1 skipped |

Итого 215 passed, 2 skipped, 0 failed — совпадает. Предсуществующих падений не встретилось.

## 3. Сверка дрейфов по коду

1. **Владение.** `services/prompt_factory.py:866-891`: `apply_release`, `activate_revision`, `import_legacy_snapshots` только делегируют в `prompt_release_policy`; собственной логики активации нет. Контракт §7 описан верно.
2. **Деплой vs owner baseline.** `prompt_release_policy.py:2270-2316`: при `PLAN_ACTIVATE_PINNED` заводская ревизия пишется в историю (`reason=factory_release_pinned`), активный текст не меняется, событие `skipped_same` + `detail_code=factory_superseded_pinned`, ветка возвращается до снятия chat-override. Без pin — активация поверх правки и снятие override (`:2357`). Совпадает с §3.2.
3. **«Одна транзакция».** `web/api/routes.py:770-807` (chat) и `:1439-1473` (global): промптные ключи первыми через `_write_prompt_items` (`JournalUnavailable` → 503, значение не пишется), непромптные настройки — вторым этапом. Таблица §3.1 и «честная граница» соответствуют коду.
4. **Три слоя аудита.** Слой 1+3 — `tests/test_prompt_field_audit.py`; слой 2+3 — `tests/test_prompt_versioning_enforcement.py`; печати и grep — `tests/test_evol018_prompt_audit.py`. Имена в §5 совпадают с файлами.
5. **Счётчики реестра.** Независимый пересчёт: 112 блоков, 111 с заводским текстом, 111 печатей, 102 метки, 39 блоков с `pg_key` (38 ключей, `character.core` — 2 блока-поля), 73 без `pg_key`. Совпадает с §2; тест `test_registry_snapshot_counts_are_stable` пинит числа. Grep-аудит — расхождение, см. F1.
6. **Снятие override только без pin.** Подтверждено пунктом 2: pinned-ветка завершается `return` до `remove_chat_override`.
7. **Baseline-указатель и пагинация без потолка.** `_BASELINE_SQL` (`:273-280`) — последнее событие `baseline_assign|baseline_clear`; `assign_baseline` пишет только событие `outcome=recorded`, повтор идемпотентен; `clear_baseline` текст не меняет. Пагинация — keyset по `(created_at, вторичный ключ)` без OFFSET (`:236-266`), `clamp_page_size` 1..200 как размер страницы, `total_known=None` (`:3822`); продуктовый путь истории использует `list_activations_page` (`:3689`), вызовов легаси `list_activations(limit=50)` вне политики нет.
8. **Замороженная legacy-история Speech.** `HISTORY_MAX_PER_BLOCK=12` остался в `services/prompt_factory.py:71` с флагом `_HISTORY_FROZEN` (`:84-94`), витрина Speech читает PG-журнал страницами (`SPEECH_HISTORY_PAGE=50`, `web/api/speech.py:969-1051`). §3.5/§3.6 соответствуют коду.

## 4. Мутации

Отчётный скрипт `evidence/pvr-s6/mutations.py --repo .`: `CAUGHT A`, `CAUGHT B`, `CAUGHT C`, `restored byte-identical: True`, `post-restore: 15 passed`.

Мои независимые мутации (другие точки, не из набора Builder-а):

| Мутация | Ожидание | Факт |
|---|---|---|
| D: удалён маршрут `POST /prompts/{key}/baseline/restore` | падает слой «одинаковая панель версий» | CAUGHT — `test_version_ui_routes_exist_for_every_prompt`, 1 failed |
| E: в каталоге скрыт другой промпт `prompts.factcheck_analyst_system_prompt` | падает слой «поле без редактора» | CAUGHT — `test_every_editable_prompt_has_reachable_surface`, 1 failed |

Файлы восстановлены байт-в-байт, `git status` после прогонов пуст. Аудит не вакуумный: `test_guard_is_not_vacuous_for_a_journalled_write` подтверждает, что запись внутри `journal_write_scope` проходит.

## 5. Находки

### F1 — §5: цифры grep-аудита не воспроизводятся (BLOCKER по приёмке пункта 2)

Требование: документ обязан описывать фактическое состояние — это и есть смысл PVR-S5.
Локация: `docs/prompt-versioning-contract.md` §5, строка «Фактический прогон: 294 файла, 69 кандидатов — 68 закрыты `code_source`, 1 в allowlist, 0 вне реестра».
Наблюдение: файлов 294 (совпадает), но кандидатов 72, закрыто `code_source` 71, allowlist 1, вне реестра 0. Проверено самим аудитом: `audit_unregistered_prompt_constants(".", blocks=[], allowlist={})` → 72; с реальным allowlist → 71; на реальном реестре → 0 нарушений.
Причина: цифры, вероятно, сняты до влития линии `rc-selfcorr` — та же ошибка «устаревшего счётчика», что и дрейф №5, который этот коммит убирал; в отличие от счётчиков реестра, эти числа тестом не запинены.
Минимальная правка: поставить 72/71 (или убрать точные числа) и, по возможности, добавить дешёвую проверку этих чисел в `tests/test_prompt_field_audit.py`.
Перепроверка: тот же прогон аудита + чтение §5.

### F2 — §8 п.5: неверно описано текущее поведение `partial_save` (BLOCKER по приёмке пункта 4)

Требование: открытые пункты честно описывают состояние.
Локация: контракт §8 п.5 («сейчас отдаётся как 500») и связанная фраза §3.1 («формат `partial_save` — открытый пункт §8»).
Наблюдение: обе ветки `POST /api/config` уже отдают 503 со структурированным `{code: partial_save, applied, rejected, prompt_snapshots}`: global — на любое исключение второго этапа (`web/api/routes.py:1463-1473`), chat — на `ChatParamsConflict` (`:796-807`); тот же формат есть в пути снятия override (`:4921-4930`). Код появился ещё в PVR-S1 (`7dd02046`), раньше этого документа. Реальный 500 возможен только на чатовом пути при не-конфликтном сбое второго этапа; UI `partial_save` не потребляет.
Минимальная правка: переписать п.5 и фразу §3.1 по факту (global → 503 `partial_save`; chat: конфликт → 503, прочие сбои → 500; UI формат не разбирает).
Перепроверка: чтение двух участков кода + текст §8 п.5.

## 6. Итог

Правило и место — принято, запрет по мемам остался пакетным. Дрейфы 1–4 и 6–8 исправлены, дрейф 5 частично (реестр верен, grep-числа нет). Аудит краснеет на всех пяти мутациях, восстановление байт-в-байт, дерево чистое. Продуктового поведения, DDL и текстов промптов срез не меняет.

**Merge: пока нет.** Нужны две документальные правки в одном файле (одна строка §5, 2–3 строки §8 п.5) и фокусная перепроверка — без повторного прогона эпика и без правок кода.

## Re-review 2 — F1 + F2 (кандидат `40cf25ea`, ветка `pv/std` @ `b5de7af4`)

**Вердикт: Approved.** Обе находки закрыты по факту, а не по формулировке. Диф `4b4d1160..HEAD` — 3 файла: контракт, этот отчёт, `tests/test_evol018_prompt_audit.py`. Продуктовый код не тронут.

### F1 — цифры §5 и их пин

Прогнал аудит сам на кандидате (не поверил документу):

| Показатель | §5 говорит | Мой прогон |
|---|---|---|
| файлов под аудитом | 294 | **294** (потолок `_AUDIT_TREE_MAX_FILES=400` не срезает) |
| кандидатов | 72 | **72** |
| в allowlist | 1 | **1** (`_QUALITY_PROMPT`) |
| закрыто `code_source` | 71 | **71** |
| вне реестра | 0 | **0** |

Способ счёта, описанный в §5, совпадает с тем, что реально делает `test_grep_audit_counts_are_stable`: пустой реестр + пустой allowlist -> 72; реальный allowlist -> 71; реальный реестр -> `[]`.

Пин проверил не чтением, а поломкой (обе правки временные, затем `Remove-Item` / `git checkout`, `git status` пуст):

- добавлен `services/_zz_tmp_review_probe.py` -> `AssertionError: файлов под аудитом 295: обновите §5 контракта и этот пин`;
- в `services/prompt_registry.py` добавлена `_ZZ_REVIEW_PROBE_PROMPT` (число файлов при этом не меняется) -> `AssertionError: кандидатов 73: обновите §5 контракта и этот пин`.

То есть пин ловит и "новый файл", и "новый кандидат", и текст ошибки ведёт прямо к §5, — ровно то, чего не хватало: прежние числа разошлись на 3 кандидата именно потому, что были сняты руками.

### F2 — что реально отдаёт `POST /api/config`

Читал код, а не §8:

- global: второй этап (`set_many`) обёрнут в `except Exception` -> `503` + `{"code": "partial_save", "applied", "rejected", "prompt_snapshots"}` — `web/api/routes.py:1456-1473`;
- chat: `except chat_params.ChatParamsConflict` -> тот же `503` (`:786-807`); прочие исключения второго этапа не перехвачены -> честный 500. П.5 называет это остатком (а);
- путь снятия override: `:4904-4930` отдаёт тот же формат (в п.5 упомянут верно);
- `partial_save` действительно появился в `7dd02046` (PVR-S1), и этот коммит — предок HEAD: ссылка в п.5 верна;
- UI: во всём `web/` слова `partial_save` нет; `persistItems` (`app.js:23599-23610`) разбирает только `409` + `code === conflict`, остальное складывает в общий `failed`. Остаток (б) описан верно.

Фраза §3.1 и п.5 теперь говорят одно и то же и совпадают с кодом.

### Ничего постороннего не изменилось

- `services/ handlers/ web/ config/ scripts/ bot.py` — пусто; `.sql` / миграций в диффе нет;
- байты мемов: `initiative.meme.joke` 95 байт `2f30ca1f9a6b`, `initiative.meme.image` 51 байт `f81fe7e4b505` — как в снимке PVR-S1; `FACTORY_SET_SHA256_12 = e9dc109330a8`, `seal_integrity() == {}`, отпечаток набора совпадает;
- наборы: `test_evol018_prompt_audit` — 11 passed; девять файлов аудита/версионирования (`test_prompt_field_audit`, `test_evol018_prompt_audit`, `test_prompt_versioning_enforcement`, `test_prompt_baseline`, `test_prompt_history_pagination`, `test_evol016_prompt_activation`, `test_evol017_prompt_history_ui`, `test_evol016_prompt_journal_v39`, `test_prompt_migrations`) — 176 passed, 1 skipped, 0 failed; `test_evol012_barrier_retired` — 8 passed.

### Некритично (не блокирует, отдельной правки не требует)

1. UI помечает как несохранённый и сам промпт, который реально записан: в `persistItems` падает вся группа. Формулировка документов ("показывает общую ошибку, хотя промпты уже сохранены") от этого не перестаёт быть верной, но при унификации (владелец PVR-S1-WRITE) стоит сказать это точнее.
2. `evidence/pvr-s1/prompt-bytes-baseline.json` расходится с текущим `direct.base.l2_writer` (`68f0233d7050` -> `44736968bc76`). К этому срезу отношения не имеет: продуктовый код в диффе пуст, реестр правили позже (5 коммитов после `7dd02046`, включая `33b62f6a` / `bf62c29a`), печати и `FACTORY_SET_SHA256_12` сходятся. Это снимок другого среза.

### Итог

F1 и F2 закрыты, посторонних изменений нет, наборы зелёные.

**Merge: да.** Слияние `pv/std` правка не блокирует; повторного ревью кода не требуется — диф документально-тестовый, а пин теперь сам сообщает, что §5 пора обновить.
