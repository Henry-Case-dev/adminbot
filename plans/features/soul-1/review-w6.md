# SOUL-1 / W6-SPEECH-UI — независимое ревью (REVIEW-W6)

- **Вердикт: Needs Fixes** (F1 — SOUL-AMD.6.4 «фактически отправленный payload» недостижим в рантайме;
  F2 — редактор правил стиля показывает серверное состояние, а сохраняет черновик; F3 — diff заводского
  сброса в реальном API не совпадает с тем, что читает UI).
- **Кандидат:** рабочее дерево поверх `c8cf77a5`, коммита/деплоя нет. Отпечатки 12 файлов слайса
  (sha256_12) совпали с `w6-speech-ui-report.md` §8 — кроме самого отчёта (в отчёте `0a4fa3c69ca7`,
  фактически `3624dbed8c4f`; остальные, включая `web/api/speech.py b85c6d63143e`, `web/app.js
  e094635999cc`, `web/index.html 69216b9222f6`, `web/static/app.css 761274ceaed1`,
  `tests/test_soul1_w6_speech_ui.py a6ad280ccd0c`, `evidence/w6/*` — совпали).
- **Стекло (инвариант):** `web/static/polygon-background.js` = blob `c2ad97d446f5e7c7b72fb46d9bb560ae3777d6c3`
  и в деплое `448cc81a`, и в HEAD, и в дереве; SVG-фильтр `#lg-lens` байт-идентичен деплою
  (`5367ec4566fc9e80`, 6298 б.); блок `--lg-*`/`backdrop-filter` в CSS идентичен (`21ed2e7655c2ca3c`);
  в диффах web/** нет строк `lg-`/`glass`/`polygon`. Изменение контраста ghost-кнопок — только внутри
  нового блока `.speech-screen`, токены не затронуты.

## Лид acceptance (W6)

| Требование | Статус | Чем проверено |
|---|---|---|
| SOUL-AMD.6.1 разделы/обычный язык | VERIFIED | витрина 7+3, live Chrome, `entry_*`/`section_*` |
| SOUL-AMD.6.2 реестр: версии/scope/сохранение/diff/reset/история/откат | FAILED (частично) | round-trip ревьюера ок; **F3** (diff заводского сброса пуст в реальном API), «тест» — кнопкой в «Попробовать» |
| SOUL-AMD.6.3 мобильный путь/редакторы 320–430 | VERIFIED | harness 320/360/390/430, live 390/320/430 |
| SOUL-AMD.6.4 Inspector: предпросмотр vs фактический payload, права, маскировка | FAILED | маскировка и preview/права ок; **F1** — снимок хода не находится в рантайме |
| SOUL-AMD.6.5 «Возможности бота» + trace + available_action_not_chosen | VERIFIED | `/capabilities`, live-раздел, тест |
| SOUL-AMD.6.6 hot-применение без рестарта | VERIFIED | ConfigCache/chat_params, повторный GET после POST |
| SOUL-10.0/10.1/10.3/10.5/16.5.0 | VERIFIED | round-trip ревьюера, live, harness |
| SOUL-10.2 редактор правил стиля | FAILED | **F2** — список/счётчик показывают сервер, правки уходят в черновик |
| SOUL-10.4 «Примеры», humor-контур, reset-learning | N/A_WITH_REASON (W4) | честный `not_implemented_w4`/`library_not_landed`, данных не выдумано |
| SOUL-AMD.8.3 «следующая генерация» | READY_FOR_LIVE (за канарейкой, flag ON) | запись — единым путём; живая генерация не проверяема до канарейки |
| SOUL-11.0 mobile-промпты из обеих точек входа | UNVERIFIED на этом слайсе | цепочка «Все инструкции» 320–430 ок; вторая точка входа — не этот слайс |

## Находки

1. **BLOCKER F1 — SOUL-AMD.6.4: снимок реального хода недостижим.**
   `web/api/speech.py:1004-1013` ищет `composer.get_manifest(chat, writer=...)` **без run_id** → ключ
   `(chat, "-", writer)` (`services/prompt_composer.py:952-958` — точное совпадение). Реальные writer’ы
   пишут манифест с `run_id=correlation_id` (uuid hex): `services/direct_chat_service.py:4267` (+ `:2833`,
   `:4476`, `:8215`; `:1975` = `usage_events.new_correlation_id()`). Доказательство (мой прогон):
   seed без run_id → `last_run_present=True`; seed с uuid → `False`. Фикстура и тест засевают манифест
   **без run_id** (`evidence/w6/dump_api_fixture.py:68-72`, `tests/test_soul1_w6_speech_ui.py:435-439`) —
   зелёные доказательства не воспроизводят рантайм-форму. Эффект: владелец после реального хода всегда
   видит «только предпросмотр»; требуемая половина Inspector’а не работает. Правка: искать самый свежий
   манифест чата среди `REAL_TURN_WRITERS` (или хранить last run_id на чат), перезасеять фикстуру/тест
   uuid-run_id.
2. **BLOCKER F2 — SOUL-10.2/16.5.1: редактор правил показывает не черновик.**
   Список/счётчик/мягкие привычки рендерятся из `speechStyle.*` (`web/index.html:7488,7494-7495,7549-7551`),
   а toggle/remove/preset/soft правят `speechStyleDraft` (`web/app.js:18565-18625`); при refresh пишется
   `speechStyleViewRules` (`app.js:18372`), который нигде не рендерится. Живой репро (Chrome, демо-сервер):
   снял галку правила → вышел из раздела → вернулся: галка снова стоит (а Save сохранит снятие);
   «Убрать» и «+ Без точек на конце» не меняют список («1 правил»), тост при этом зовёт «проверьте и
   сохраните»; после изменения длины черновика index-based действия молча игнорируются. Правка: рендерить
   списки/счётчик из черновика (как Core/Expression) + harness на add/remove/повторный вход.
3. **BLOCKER-small F3 — SOUL-AMD.6.2: diff заводского сброса в реальном API другого вида.**
   `services/prompt_factory.py:329-357` отдаёт `diff={added_lines,removed_lines}` + `current_chars/
   factory_chars`, а UI читает `diff.same/before_chars/after_chars` (`web/app.js:18495-18498`,
   `web/index.html:7981-7985`) → «было undefined → станет undefined зн.». Harness это скрыл рукописным
   стабом (`tools/ui_soul1_w6_speech_e2e.py:226-232`), хотя заголовок харнесса обещает формы из реального
   слоя. Правка: читать `changed` + `current_chars/factory_chars` (или вернуть единую форму с сервера);
   стаб /reset брать из реального ответа.
4. **Процесс: requirements_gate — FAIL.** `check --stage review --slice W6` → exit 1: строки AMD.6.1-6.6/
   8.3/0.3 в карте PENDING (evidence не внесён Builder’ом), candidate_commit карты не совпадает с деревом
   (коммита нет). До родительского Approved нужны evidence-записи и привязка кандидата.
5. **Minor (не блокирует):** guard-тест `test_writes_go_through_registry_api_only` фальсифицируем только
   для двух литеральных шаблонов (мой scratch-эксперимент: `cache.set(spec.pg_key, ...)` и
   `cache.set("prompts.*", ...)` тест ловит; запись через переменную — нет). Инспекцией прямых записей
   `prompts.*` из UI-слоя нет; тексты идут только через `write_speech_value`/фабрику; документы новых
   сущностей (`character.core` мета, `character.expression`) пишутся на существующий `ConfigCache`/
   `chat_params` — по дизайну, второго config-сервиса нет.
6. **Minor:** `_effective_after_write` (`web/api/speech.py:1576-1586`) при чат-записи возвращает
   эффективное значение ГЛОБАЛЬНОГО слоя (chat_value=None); UI поле не использует.
7. **Док-неточность:** `requirements-coverage.md` говорит «65 блоков», фактический реестр — 77 (в отчёте 77).
8. **Наблюдение:** `/speech/try?generate=true` гейтится правом просмотра — чатовый контент-админ может
   инициировать один платный вызов на вариант (бюджет/ключи проходят штатный `LLMClient`). Для канарейки
   стоит решить явно.

## Что проверено исполнением (мои прогоны)

- **Путь записи:** round-trip ревьюера (изолированный кэш): global→chat байт-изоляция, сброс чата →
  наследование, заводской план без записи, apply → заводской текст, откат → прежняя ревизия,
  пустая запись 409; provenance `owner_edit`.
- **RBAC:** denied-роль → 403 на всех 18 маршрутах; контент-админ чата → 403 на глобальных записях и
  Inspector’е, 200 на чатовых; `edit_persona` → глобальные записи + Inspector 200. Новых прав нет.
- **Inspector-честность:** UI не удалось заставить показать предпросмотр как отправленное (сервер даёт
  `sent` только из `REAL_TURN_WRITERS`); маскировка: `sk-live-...`, `token=...`, `5885953495` в JSON
  Inspector’а отсутствуют (в `preview.system_masked` → `***`/`[id]`), обычный текст цел.
- **UI/harness (мой повтор):** failures=0, POST=12, 88 кадров; pageOverflow=0 на 320/360/390/430/768/1024/
  1440 и landscape; minTap=44; padding 12px; сплит 1 колонка ≤768 и 2 на 1024/1440; live Chrome 390/320/430:
  overflow 0, minTap 44, витрина 1 колонка.
- **Навигация:** живой Chrome — хаб «ИИ» ровно 5 карточек в прежнем порядке; вход 44px внутри «Личность и
  стиль»; нижняя навигация «Ещё • ИИ» на месте; `test_webapp_f5_round1025.py:305` и IA-inventory проходят.
- **Тесты:** node 6/6 JS-UNIT-OK; `gen_param_registry_round1025.py --check` OK (572==REGISTRY);
  `tests/test_soul1_w6_speech_ui.py` 18 passed; IA+f5 26 passed; периметр
  `-k "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or glass or persona or prompt or registry or catalog"`
  — **3782 passed / 0 failed** (10244 deselected, 107 s; у полосы в отчёте 3781 — их прогон старше одного
  из 18 тестов файла). Существующие e2e-харнессы соседней полосы asap8 (shell/fullscreen) не перезапускал:
  они пишут в её evidence (DO_NOT_TOUCH); навигационный пин закрыт f5-тестом и живой проверкой.
- **Секции-честность (live):** «Юмор» — библиотека выключена, W4; «Примеры» — `not_implemented_w4`;
  «Обучение» — «отсутствие реакций — не провал», контур W4; «Выражение» — `runtime_wired=false` + причина;
  «Попробовать» — «ничего не отправляется в Telegram и не создаёт постоянных уроков», платный вызов только
  по явной галке (код: `delivery.telegram_send=false`, `lessons_created=0`, в `_generate_variants` нет
  send/lesson-путей).

## Кандидат/доказательства

- Кандидат: рабочее дерево, 12 отпечатков §8 отчёта совпали (см. выше); инцидентальные изменения соседних
  полос (asap8, disk_retention, W10-доки) в рабочем дереве присутствуют и к этому слайсу не относятся.
- Переиспользовано: `evidence/w6/ui-report.json`, фикстура, снимки (проверены выборочно глазами); новое:
  round-trip ревьюера, RBAC-пробы, проба run_id Inspector’а, проба маскировки, живой Chrome (хаб/персона/
  стиль/Inspector/секции, 390/320/430), повтор harness’а, guard-фальсификация в scratch,
  сравнение стекла с деплоем.

## До канарейки

1. Починить F1, F2, F3 (после — маленькая перепроверка: проба run_id + живые add/remove/re-entry стиля +
   diff заводского сброса на реальном ответе; повтор W6-тестов и harness).
2. Внести evidence в карту W6 и привязать кандидата (gate exit 0).
3. Живая генерация/канарейка — отдельный гейт владельца (этот слайс ничего не отправляет).

---

## RECHECK-W6 — перепроверка исправлений F1/F2/F3 (второй вердикт)

- **Вердикт: Needs Fixes.** F1/F2/F3 и оба extra закрыты и подтверждены в рантайме (ниже), но доставленные
  байты деградировали по EOL: три web-файла CRLF-only → 2 красных node-теста, «периметр 3786/0» не
  воспроизводится (факт 2 failed / 3784 passed), заявленные финальные отпечатки совпадают лишь с
  LF-нормализованной формой. В таком виде коммит/канарейка запрещены.
- **Кандидат:** то же дерево поверх `c8cf77a5`, коммита нет. Raw sha256_12: `web/api/speech.py a50854e0c77e`
  (CRLF=2259, одиночных LF=0), `web/index.html b80158b59deb` (CRLF=10517, LF=0), `web/app.js 1eaebd6ba0f1`
  (CRLF=21983, LF=0); LF-нормализованные — `d1fec786ee6b`/`786fe44e4f94`/`cea14985241d` (= заявленные
  в §Fix pass). Остальные файлы набора — raw-совпадение: `app.css 761274ceaed1`, `app.py 069737d43b89`,
  `tests/test_soul1_w6_speech_ui.py 5b61a663cf65`, `tools/ui_soul1_w6_speech_e2e.py b71312860739`,
  `evidence/w6/dump_api_fixture.py a9c2373eda53`, `tests/test_ia_inventory_round1025.py 279848076989`.
- **Блокер B1 (новый, canary-стоп): EOL-регрессия от fix-pass.** `OPENCODE_WORKFLOW_SCRATCH/w6-fix/
  mutation_guard.py` восстанавливает файлы через `read_text→write_text` (Windows: LF→CRLF), self-check
  «restored=True» EOL-слеп; mtime 8:44:18/28/33 — guard перезаписал speech/index/app ПОСЛЕ нормализации
  полосы, финальные байты не перепроверялись. Репро на текущих байтах: `test_js_unit_round1025_hotfix8_shell_aurora`
  и `test_js_unit_round1026_s7_log_summary_filter` — красные (мой повтор: 2 failed in 3.08s); на LF-mirror
  обе PASS (падение чисто EOL). Периметр `-k "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or
  glass or persona or prompt or registry or catalog"` = **2 failed / 3784 passed** (10244 deselected).
  `git hash-object`: `c0453c015c85` / `33f6fcac5cf9` / `9391bbbdd87f` — коммит as-is сохранит CRLF-блобы.
  **Минимум:** байтовая LF-нормализация ровно этих трёх файлов последним шагом (guard — писать bytes),
  повтор node×2 + периметра (цель 3786/0), raw-отпечатки заново → возврат в recheck.
- **F1 — VERIFIED (закрыт).** Мой probe рантайм-формы (uuid run_id): старый lookup без run_id слеп; новый
  находит последний реальный ход чата (`last_run_present=True`, run_id/writer видны) даже при более новом
  preview; повторные чтения store не мутируют (read-only); новый реальный ход с другим writer выигрывает;
  чужой чат пуст; legacy-fallback и preview-only честные. Фикстура/тест засеяны uuid
  `1ecc6ec04e7a4051b2ea0cc9091174e1`, ассертят отсутствие старого ключа.
- **F2 — VERIFIED (закрыт), live Browser Use (демо-сервер :8815):** снятая галка переживает выход/возврат +
  бейдж «черновик не сохранён»; пресет 1→2 сразу, счётчик «2 правил», id `trailing_period.hard.strip`;
  toggle/select по индексу после смены длины; «Убрать» 2→1 и действие по индексу после; привычки 1→2→1;
  stale-index → честный тост «Список правил изменился: обновите раздел и повторите».
- **F3 — VERIFIED (закрыт).** Реальный `/reset(apply=false)`: `changed=True, current 2882, factory 2835,
  diff {−2/+0}`, без `before_chars/after_chars` — совпадает с фикстурой по UI-полям; live-тост и карточка
  блока: «было 2882 → станет 2835 зн. (строк −2 / +0)», «undefined» нет; стаб в харнессе убран
  (`_post_body` читает FIXTURE).
- **Extras — VERIFIED.** «Вернуть заводской» на «Характере»: live fetch-лог `POST
  /api/speech/block/core.personality/reset` (`apply:false`, затем `apply:true`). Тест выбора тостов читает
  все тосты (any), stale-тост не вакуумный. Guard-фальсификация: `prompts.*` переменным ключом → RED;
  подмена текста Core из UI-слоя → RED; метаданные → GREEN; симуляция регресса через
  `_effective_after_write` → RED.
- **Стекло — VERIFIED (инвариант):** `web/static/polygon-background.js` blob
  `c2ad97d446f5e7c7b72fb46d9bb560ae3777d6c3` (файл не изменён vs HEAD); `#lg-lens` (6298 б.) — контент
  tree==HEAD, `5367ec4566fc9e80` (raw-разница только из-за CRLF, тот же B1); строки `--lg-*`/`backdrop-filter`
  в app.css tree==HEAD (`89cda50a6e618ea5`). Артефакты asap8 после прогонов стекла восстановлены
  байт-в-байт (28/28).
- **Счётчики (мои прогоны на этом кандидате):** `tests/test_soul1_w6_speech_ui.py` — **22 passed**;
  harness `tools/ui_soul1_w6_speech_e2e.py` — failures=0, POST=16, shots=94 (заметки идентичны прогону
  полосы; копия — scratch `review-w6-recheck/ui-report-lane.json`); периметр — см. B1.
- **Инцидентально (не блокирует):** `requirements-coverage.md` всё ещё «65 блоков»; minor #6
  (`_effective_after_write`) не трогался; коммита нет — процессный пункт «привязать кандидата и evidence
  в карте» остаётся открытым.

## RECHECK-W6-2 — финальная перепроверка фикса дубля `lessonAction` (третий вердикт)

- **Вердикт: Approved** (в объёме фикса дубля; открыт только процессный пункт родителя, см. ниже).
- **Кандидат:** то же дерево поверх `c8cf77a5`, коммита нет. Полные raw sha256 совпали с заявленными:
  `web/app.js 401a40a5322a57630b3845aee354d2665cfb2bfed15ac22fa3c3968418dff852` (1156860 б., CRLF=0/CR=0/LF=21983);
  `web/index.html 8d86cd1a0a0f0e75dbe194dac243d988ad64a7d1c8d21f5af090daf14f2dc09d` (790816 б., CRLF=0/CR=0/LF=10517);
  сторож `tests/js/app_methods_dup_keys_guard_test.js 68243a476f535b3f1afc6b25ce05028e50a83c593a4fb6a275bf6175f3e574c9` (CRLF=0).
  LF-only, размеры +6/+12 = дважды «speech», новых строк нет.
- **Дифф ровно 3 строки** (мой независимый построчный diff против prefix-байт `cea14985241d`/`786fe44e4f94`,
  которые отпечатались ровно как заревьюенный pre-fix LF-кандидат): app.js:18884 `lessonAction`→`speechLessonAction`;
  index.html:7878/7881 → `speechLessonAction(...)`. Других отличий в этих двух файлах нет.
- **Память MCA-16 восстановлена (поведением):** `app.js:7728/7768` не тронуты; мой независимый Vue-stub probe
  (написан заново, не из кода сторожа): `lessonAction(l,'correct',{applicability,exceptions})` → POST
  `/api/memory/lessons/action` с полным payload + `loadLessons()`, `loadSpeechSection` НЕ вызывается;
  на prefix-байтах probe красный ровно исходным дефектом («payload lost», чужой раздел); `round1039` → `MCA16-EXP-OK`.
- **Раздел «Речь» использует свой метод:** кнопки «Пауза»/«Одобрить» (index.html:7878/7881) → `speechLessonAction`
  (app.js:18884); probe: POST c lesson_id/version/action + `loadSpeechSection('learning', true)` + тост, методы
  разные; то же проверяет поведенческая часть сторожа. Харнесс эти кнопки НЕ нажимает (только стаб
  `/api/memory/lessons/action`), поэтому поведенческое доказательство — Vue-stub (мой probe + сторож), не харнесс.
- **Сторож фальсифицируем (мои 6 прогонов):** current → `METHODS-DUP-KEYS-OK blocks=6 keys=937 behavioral=ok`;
  prefix-пара → FAIL (`lessonAction` ×2 @ 7728/18884, нет `speechLessonAction`, TypeError `this.loreErrText`);
  опечатка в @click → FAIL только по ссылке; half-fix (W6-имя откатано только в app.js) → FAIL (дубль + 2 ссылки
  + поведение); `_prefersReducedMotion` с ДРУГИМ телом, ровно ×2 → FAIL; ×3 идентичных → FAIL.
  `KNOWN_DEAD_DUPES` реальный дубль не глушит ни в одном из вариантов.
- **Прогоны на этих байтах (мой повтор):** node `tests/js/**` — 85 файлов, 0 падений; `tests/test_soul1_w6_speech_ui.py`
  — 22 passed; харнесс — failures=0, POST=16, shots=94; периметр
  `-k "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or glass or persona or prompt or registry or catalog"`
  — **3786 passed, 0 failed** (10244 deselected, 77.8 s); стекло: `W2-SHELL-E2E-OK`, fullscreen 7/7 PASS.
  Артефакты asap8 и `evidence/w6` после прогонов восстановлены байт-в-байт (132/132 файла, 0 расхождений;
  в evidence/w6 разошлись только 94 перегенерированных shot-PNG, report идентичен — восстановлено из снимка).
- **Инварианты стекла:** polygon blob `c2ad97d446f5e7c7b72fb46d9bb560ae3777d6c3` (worktree==HEAD);
  `#lg-lens` 6298 б. `5367ec4566fc9e80` ==HEAD; `--lg-*`/backdrop-filter 104 строки `89cda50a6e618ea5` ==HEAD;
  `app.css 761274ceaed1`; остальные файлы слайса — совпадение с заревьюенным кандидатом (`speech.py d1fec786ee6b`,
  `app.py 069737d43b89`, тест `5b61a663cf65`, харнесс `b71312860739`, фикстура `a9c2373eda53`/`226252e643a8`,
  ia-инвентарь `279848076989`); дифф `web/**` — только 4 известных файла W6.
- **До коммита W6 блокеров нет** (EOL-регрессия закрыта ранее, функциональный дефект закрыт здесь). Открыт только
  процессный пункт родителя: запись evidence/привязка кандидата в карте W6 + `requirements_gate check --stage review`.
  Инцидентально (не блокирует): в корне репозитория лежит untracked `OPENCODE_WORKFLOW_SCRATCH/` (скретч полосы) —
  в коммит не добавлять; guard несёт `TEST-LIFECYCLE: REGRESSION owner=soul-1/W6` — корректно.
