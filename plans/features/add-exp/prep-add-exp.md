# ADD-EXP — prep: сверка с master, очередь, фазы (PM-PREP-ADD-EXP, 19.10.2026)

Лейн: PM-PREP-ADD-EXP. Режим: **read-only по проду** (SSH к проду **не использовался** — там идёт ACCEPTANCE-94; Ф0 — один read-only коннект после её завершения); записи — только `plans/features/add-exp/**`; push — нет.

| Артефакт | Назначение |
|---|---|
| `source-add-exp-2026-10-19.md` | VERBATIM-снапшот `plans/current_task.md` строк 1735–1789 (sha256 `2a7d0c0297dc56591396372d86c4176d3b64924e2e75194e45fd33c2052f7d9f`) |
| `requirements-map.json` | `openworkflow-coverage-v1`: 20 inventory + 17 manual = **29 required + 8 context**, 5 live (postdeploy) |
| `prep-add-exp.md` | этот документ |

План-гейт (verbatim): `stage=plan inventory=20 manual=17 scoped=0 errors=0` (EXIT 0).

## 1. Сверка §0–§4 со статусом по коду master (без прода)

Легенда: **AIV** = уже реализовано и подтверждено (карты/тесты/релизы); **PARTIAL** = часть есть, дельты нет; **BROKEN** = не работает / не подключено; **NEW** = новое; **CONSTRAINT** = запрет/инвариант.

| # | Пункт ADD-EXP | Статус | Якоря (master / карты) | req_id (карта add-exp) |
|---|---|---|---|---|
| §0-1 | Скриншот «Мат: Как в характере (естественный)», мата в ответах нет; проверить на фактических последних ответах, а не по впечатлению | NEW (диагностика) | прод-аудит 18.10: `character.expression` — **0 строк** в `bot_settings` (persistence-audit §5); после 2.58.90 владелец мог сохранить значение — уточнить в Ф0 | EXP-DIAG-PROD |
| §0-2 | Master-факты: `profanity` = inherit/off/allowed; «мат допустим … не обязательный»; весь слой — мягкая рекомендация; `runtime_wired=False`; composer умеет исключать слой | ПОДТВЕРЖДЕНО | `web/api/speech.py`: 115–127, 148–153 (151), 754–780, 814–818; `services/prompt_composer.py`: 97–98, 152, 1280–1312 | EXP-DIAG-PAYLOAD |
| §0-3 | Установить фактический prod runtime и проверить конечный LLM payload **до** любых изменений; Inspector/Preview — не доказательство | NEW | известно из evidence: `UNIFIED_COMPOSER_ENABLED=1` в проде (release 2.58.86/2.58.90; `p0-save-init-ux/evidence/audit-2026-10-18/probe_live_readonly.json`), legacy withheld=11; Expression на живых путях — absent по коду (см. §3-2); Ф0 подтверждает | EXP-DIAG-PAYLOAD |
| §1-1 | Явные значения «без мата / эпизодически / часто» вместо «Как в характере (естественный)» | NEW | сейчас только `off`/`allowed` (`speech.py:151`, 115–127); секция «2. Манера речи» (`app.js:19255–19263`; `index.html:8082+`) | EXP-UI.MODES / .OFF / .OCC / .FREQ |
| §1-2 | `inherit` — только наследование; показывать effective-значение и источник global/chat; в глобальном scope — явное разрешение режима | PARTIAL | наследование реализовано (`speech.py:723–739`; UI `speechSourceText(inheritance)`); в global scope «эффективный режим» не разрешается явно (документа нет → `present:false`) | EXP-UI.INHERIT |
| §1-3 | Миграция `allowed` → `occasional` без потери данных; `frequent` — только по согласованию; сохранить override/revision/history/factory reset/Core | NEW | revision/history хранятся (`speech.py:2288–2341`); кода миграции нет; персистентность уже исправлена (P0A-PERSIST 29/29 VERIFIED, 2.58.90) | EXP-UI.MIGRATION |
| §2-1 | Позитивные инструкции по режимам; «мат разрешён/естественно/необязателен» — не единственное правило; frequent — явная регулярность | PARTIAL | слой есть (`render_expression_text` 754–780; effect-тексты `off`/`allowed`); occasional/frequent и сильные формулировки — новые; `allowed`-текст = ровно слабая формулировка из претензии | EXP-INSTR.POSITIVE |
| §2-2 | Owner-approved few-shot набор (различает off/occasional/frequent), без метакомментариев, по бюджету, не дублируя Sample Library | NEW | Sample Library существует: `services/mca_sample_library.py` (humor_samples, 18 сидов, `owner_approved`, гейт `humor_library_enabled`); композер-слой 9 few_shot (`prompt_composer.py:1358–1386`) — переиспользовать, не дублировать | EXP-INSTR.FEWSHOT |
| §2-3 | Не постпроцессор; не ломать морфологию, факты, ссылки, код, цитаты, Telegram entities | CONSTRAINT | постпроцессора вставки мата нет; W3 style_policy — bounded правила (`style_policy.py:70–71`; RULE_KINDS без profanity) — не создавать и не ломать | EXP-INSTR.NOPOST |
| §3-1 | Проверить чтение/запись `speech.py`, `character.expression`, `render_expression_text()`, per-chat inheritance, revision/conflict, hot reload; исправить write/read-after-write без имитации успеха | AIV (P0) + verify-delta | P0A-PERSIST 29/29 VERIFIED (release 2.58.90: PG-first ConfigCache, chat-scope записи ×10, честные 409/503); SOUL-AMD.6.6 VERIFIED (hot reload); перепроверить в контексте новых режимов | EXP-RUNTIME.READSAVE; ADD-1.E6 |
| §3-2 | Expression реально подключён в Direct/Initiative; LAYER_EXPRESSION с ревизией и без `expression_absent`; `budget_excluded`; жанровые исключения | **BROKEN (не подключено)** | `ExpressionSettings` конструируется только в preview (`speech.py:1458`, writer `speech_ui_preview`); живые сборки: `direct_chat_service.py:4373–4398` (без `expression=`), `mca_authorial_speech.py:96–135` (без) → на живых ходах слой пропускается `expression_absent`; `runtime_wired=False` (814) и предупреждение в UI (`index.html:8096–8097`) — честно | EXP-RUNTIME.WIRING; ADD-1.E1 |
| §3-3 | Приоритет Core/Expression/Style/жанр/запрос; legacy-промпты не в active runtime | PARTIAL | `LAYER_ORDER`/OWNERS/бюджет (`prompt_composer.py:47–142`); single Core; legacy withheld=11 (release 2.58.86); контракт при конфликте «Core свободно» vs «Expression frequent» не формализован | EXP-RUNTIME.PRIORITY |
| §3-4 | Реальный complete LLM payload и результат; не подавляет ли постпроцессор/жанровый Writer/стиль/модель | NEW | доказательство — только живой payload (Ф0 и Ф6); Inspector/preview не считается (совпадает с честностью SOUL-10.P3) | EXP-RUNTIME.PAYLOAD |
| §3-5 | Классы диагностики: `policy_not_injected` / `composer_excluded` / `model_ignored_instruction` / `postprocess_changed` / `provider_limitation` / `unknown` | NEW | в коде классов нет | EXP-RUNTIME.DIAG |
| §4-1 | 20–30 контролируемых примеров; измерение частоты; `frequent` заметно чаще `occasional`; `off` исключает; без сотен платных вызовов | NEW | живой набор CFG-07D.3/D.4 (PENDING) — тот же набор использовать | EXP-ACCEPT.LIVE-SET |
| §4-2 | Direct/Initiative/жанры; override/GLOBAL; без рестарта; reread после сохранения; preview vs production trace; изоляция `frequent`-чата от `off`-чата | NEW (live) | наследование chat>global есть; изоляция scope — P0A-UX-SCOPE VERIFIED | EXP-ACCEPT.ROUTES |
| §4-3 | Админка: человекочитаемые описания режимов + реальное effective; preview честный; успех — после runtime-применения | PARTIAL | UI-описания и preview есть (`index.html:8082–8126`); preview — детерминированный рендер без реального прогона; `runtime_wired=false` виден | EXP-ACCEPT.PREVIEW |
| §4-4 | Reviewer + отчёт «было/стало», где блокировалось, версия prod, что требует owner E2E | процесс | — | EXP-ACCEPT.REVIEW |
| §П | Порядок: в составе SOUL-1/CFG-07/Speech UX; не прерывать; map не обнулять; после деплоя — продолжить очередь | процесс | CFG-очередь серийная (ADD-0.1, план CFG); текущая волна в полёте | EXP-REG.QUEUE |
| §К | Критерий завершения: режимы реально меняют ответы и доходят до production LLM, а не только существуют в форме/предпросмотре | NEW (live) | — | EXP-ACCEPT.CRITERION |

**Пометка о честности:** ревью W6 сознательно приняло `runtime_wired=false` + причину для SOUL-10.3 (VERIFIED). Дельта ADD-EXP — **не регрессия**, а незакрытая часть: слой Expression никогда не был подключён на боевой путь, а UI уже честно это показывает. Ранее сохранённый `allowed` («как в характере») не влиял на генерацию вообще — это и объясняет наблюдаемое «мат отсутствует»; подтвердить фактами в Ф0.

## 2. Зависимости и оптимальная очередь

### Предпосылки и пересечения
- **SOUL-1** — стабилен: Core/Composer/Style/hot reload VERIFIED (SOUL-04.2, SOUL-10.3/10.P3, SOUL-16.P1, SOUL-AMD.6.6); capability-контур §5/§5.1 (W10) VERIFIED — не пересобирать (ADD-1.E2).
- **P0 (save-init/UX)** — закрыт: P0A-PERSIST/P0A-UX 29/29 VERIFIED (2.58.90). Персистентность и UX-волна переиспользуются (ADD-1.E5/E6).
- **CFG-07** — строгая серийная очередь: CFG-06 → **CFG-07A → CFG-07B** → CFG-07C (ADD-0.1; `cfg/plan.md`). CFG-07B владеет параметром мата (`profanity_use`, factory ON, GLOBAL/CHAT, Inspector); CFG-07A.1 (payload trace) = Ф0 ADD-EXP; CFG-07B.4 уже допускает уровень интенсивности «если потребуется тестами».
- **add-tr** — Speech-пересечения: ADTR-POSTGEN-VOICE VERIFIED (единый источник голоса); DOD4/VERIFY PENDING (UI Android). Не дублировать (ADD-1.E7).
- **Текущая волна 19.10** (CFG-02B/C, vision, add-tr) трогает `direct_chat_service.py` и web — старт ADD-EXP возможен только в безопасной точке (не сейчас).

### Где место ADD-EXP — рекомендация: **внутри слота CFG-07B** (Ф0 — раньше, read-only)
Обоснование:
1. **Один владелец пересечения** (ADD-1 dedup): CFG-07B уже владеет параметром мата и его runtime-эффективностью; строки ADD-EXP ложатся на CFG-07B.1–8 / D.3 / D.4 (интенсивность, миграция, подключение, Inspector, защищённые цитаты). Отдельная реализация = второй параметр и второй проход — прямое нарушение «не дублировать».
2. **Те же файлы**: `web/api/speech.py`, `services/prompt_composer.py`, `services/direct_chat_service.py`, `web/app.js`, `web/index.html`, `services/style_policy.py`, tests. Двойной проход = второй ревью/деплой и риск расхождения поведения.
3. **ADD-EXP сам требует** «в составе существующих SOUL-1 / CFG-07 / Speech UX HOTFIX», «не прерывать», «не вытеснять другие требования» → вставка раньше CFG-06 вытесняла бы CFG-06 и переставляла строгую очередь без решения владельца.
4. **Ф0** (prod payload-диагностика) — read-only, одна волна; может быть выполнена раньше (сразу после ACCEPTANCE-94); фактически это CFG-07A.1.

Альтернатива «отдельным слотом раньше CFG-06» — отклонена по умолчанию (двойная реализация + перестановка очереди без требования источника). Если владелец отдельно захочет ускорить пользовательский эффект — это его явное решение о перестановке; источник такого не требует.

### Порядок в общей очереди
| Точка очереди | ADD-EXP-часть | Примечание |
|---|---|---|
| Сразу после ACCEPTANCE-94 | **Ф0** — 1 read-only коннект | не блокирует очередь; evidence в `evidence/f0/` |
| Пока идёт CFG-06 (и текущая волна) | **Ф1** — дизайн (read-only) | контракт, инструкции, few-shot черновик; файлы не мутируются |
| Слот CFG-07A/07B | **Ф2–Ф5** | единый кандидат покрывает и CFG-07B-строки, и EXP-строки |
| Выкат слота | **Ф6** | deploy + живой набор 20–30 |

### Внутренние зависимости слайсов (write scope)
- `EXP-RUNTIME` (контракт + подключение + диагностика) → `EXP-UI` (режимы/миграция/effective-источник) → `EXP-INSTR` (инструкции/few-shot/жанровые исключения) → `EXP-ACCEPT` (набор/изоляция/превью-честность/Reviewer).
- Все три первых трогают `web/api/speech.py` — по умолчанию **serial joins** (документированные зависимости). Параллель возможна только если Ф1 зафиксирует непересекающиеся write scope (кандидат: few-shot/сиды Sample Library ↔ UI `app.js`/`index.html`).
- `EXP-ACCEPT` — после всех; live-часть (5 строк postdeploy) — на выкате.

| Slice | required | live postdeploy | Состав |
|---|---|---|---|
| EXP-UI | 8 | — | OFF/OCC/FREQ/MODES/INHERIT/MIGRATION + ADD-1.E3/E5 |
| EXP-INSTR | 4 | — | POSITIVE/FEWSHOT/NOPOST + ADD-1.E7 |
| EXP-RUNTIME | 11 | WIRING, PAYLOAD | READSAVE/WIRING/PRIORITY/PAYLOAD/DIAG + DIAG-PROD/DIAG-PAYLOAD + ADD-1.E1/E2/E4/E6 |
| EXP-ACCEPT | 6 | LIVE-SET, ROUTES, CRITERION | LIVE-SET/ROUTES/PREVIEW/REVIEW/CRITERION + REG.QUEUE |

## 3. Фазы

- **Ф0 — payload-диагностика на проде (после ACCEPTANCE-94; 1 read-only коннект).** Одним скриптом (правила fail2ban: один логин, короткий таймаут): сохранённый документ `character.expression` (global + chat overrides), ревизия/updated_at, effective gates (`UNIFIED_COMPOSER_ENABLED` и речевые оси), deployed SHA; последние реальные ответы бота (набор для наблюдения мата); манифест/лог последнего Direct-хода — слой `expression`: `absent`/`present`, причина (`expression_absent`/`budget_excluded`); подтверждение, что legacy withheld. Evidence: `plans/features/add-exp/evidence/f0/`. **Никаких изменений и деплоя.**
- **Ф1 — дизайн (Architect + PM; read-only).** Контракт одного параметра: единое effective-правило `profanity_use` (или согласованное расширение) со значениями off/occasional/frequent; `inherit` — только наследование; миграция `allowed`→`occasional` с доказанной совместимостью; инструкции по режимам (тексты); few-shot черновик (owner-approved механизм из Sample Library); карта жанровых исключений (цитаты, фактчек, ошибки API, тех. сводки); классы диагностики; бюджет примеров. Может идти параллельно CFG-06 — файлы не мутируются.
- **Ф2 — RED.** Падающие тесты: значения/нормализация/миграция; effective-источник; манифест LAYER_EXPRESSION с ревизией и без `expression_absent` на Direct/Initiative; диагностические классы; изоляция чатов; жанровые исключения; отсутствие постпроцессора; OFF-паритет.
- **Ф3 — IMPL.** Реализация в слоте CFG-07B (единый кандидат).
- **Ф4 — GREEN + blast radius.** Затронутые наборы тестов, OFF-паритет, бюджеты слоёв, регрессии «Речи и характера» (P0A-UX), отсутствие влияния на другие требования.
- **Ф5 — evidence + независимый Reviewer.** `check --stage review --slice … --candidate …`; отчёт «было/стало», где блокировалось правило, что исправлено.
- **Ф6 — deploy + живой набор 20–30.** Postdeploy: три режима на одинаковом наборе ситуаций; изоляция `frequent`/`off`; переключение без рестарта; reread после сохранения; preview vs production trace; release-гейт.

## 4. Риски

1. **Бюджет LLM-примеров.** Few-shot идёт слоем 9 после expression/humor в бюджетной очереди (`prompt_composer.py:139–142, 1358–1386`) — при перерасходе примеры вытесняются первыми (`budget_excluded`). Нужен компактный отбор и измерение, что примеры реально доезжают; живой набор — не сотни платных вызовов.
2. **Жанровые исключения.** Factcheck/Summary/жанровые Writer-маршруты (`mca_authorial_speech`) и формат CFG-06E/F: мат не форсируется в цитатах/фактчеке/ошибках API/тех. сводках; не сломать контракты жанров, работающих параллельно в той же эпохе.
3. **Конкуренция Core/Style.** Core («мат — естественная часть речи») — мягкое разрешение; Expression задаёт интенсивность; Style Policy — форму. Нужен явный контракт приоритетов (без двойных инструкций), legacy-каноны не возвращать (сейчас withheld=11).
4. **«Не постпроцессор».** Соблазн детерминированной вставки слов; запрет зафиксирован (EXP-INSTR.NOPOST); существующие валидаторы (W3) и будущий egress-guard CFG-07C не должны ни вставлять, ни вырезать мат вопреки режиму.
5. **Провайдеры/модели.** Разные LLM следуют стилю по-разному; `provider_limitation`/`model_ignored_instruction` не маскируются как исправление (классы диагностики).
6. **Миграция и данные.** `allowed`→`occasional` без потерь override/revision/history/factory reset; в проде документ мог отсутствовать (0 строк на 18.10) — Ф0 уточняет; ни один чат не переводится в `frequent` без согласования.
7. **Параллельные писатели.** Текущая волна (add-tr/vision/CFG-06) трогает `direct_chat_service.py`/web — ADD-EXP стартует только в безопасной точке; внутри ADD-EXP слайсы сериализованы по `speech.py`.

## 5. Что требует owner-входа

- **Единственный пункт — OPTIONAL_FEEDBACK:** черновик owner-approved few-shot набора покажем в отчёте (Ф1/Ф5); правки владельца по желанию, через существующий редактируемый механизм (Sample Library/`owner_approved`). **Не блокирующий гейт.**
- Новых обязательных согласований нет: PET_PROJECT (стоячее согласие на выкат проверенных функций), device-чек-листы отменены 18.10, живые проверки — агентские (Ф6). Human Gate preflight: новых `USER_DECISION` не найдено — эффективный дефолт после миграции определён источником (`allowed`→`occasional`; `frequent` — только по явному выбору владельца), factory ON из CFG-07B.1 совместим (разрешение мата сохраняется).
