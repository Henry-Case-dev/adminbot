# BINDING-FINAL-258118 — привязка карт к задеплоенному `2.58.118`

Дата: 24.10.2026 · Lane: `PM-FINAL-BIND-258117` · Worktree: `C:\Code\Python\adminbot-wt258115`
(ребейз на `origin/master` = `1ae165f9`).
Источник фактов деплоя: `plans/features/_audit-2026-10-23/release-258118/deploy.md`
(в репозитории, коммит `1ae165f9`). Промежуточный выкат `2.58.117` (`724b77ac`) сохранён как
историческая запись: `plans/features/_audit-2026-10-23/release-258117/deploy.md`
(sha256 `07f6e0dd2cb83a4c2333d3d1db422413db22fa8eaf3564d580a2535b110ebb3e`).

**Почему привязка на `9ed68ee8`, а не на `724b77ac`:** пока шла эта полоса, поезд выкатил
`2.58.118` (`9ed68ee8`) и прод переведён на него. Привязка к более старому коммиту сделала бы
release-гейт зелёным по неверной идентичности, поэтому карты привязаны к фактически работающему
коду; `e9f7595b` → `724b77ac` → `9ed68ee8` сохранены в `produced_on_original`.

## 1. Привязка

| Параметр | Значение |
|---|---|
| `candidate_commit` (все три карты) | `9ed68ee8ab2b874d45832e57bed2deaa5d5b76b7` |
| `deployed_commit` (все три карты) | `9ed68ee8ab2b874d45832e57bed2deaa5d5b76b7` |
| Прод-версия | `2.58.118`, healthz 200 (`{"status":"ok","version":"2.58.118"}`), MainPID `858447`, `NRestarts=0` |
| Дельта поезда | `724b77ac..9ed68ee8`: только `README.md`, `config/settings.py` (версия), `services/direct_chat_service.py`, тесты и `plans/**` |
| Каноны | L1 `6c2ddc17c998`, L2 `83ff62bbee40`, `direct_chat` `f30c6d73da82`, `synthesizer` `6bae7eb26bc3`, fingerprint `0163a686c401` — до/после идентичны |
| Миграции | `prompt_rollback`=0, фактических миграций нет; `prompt_migration`=17 — только «уже новый канон»/«кастом юзера — НЕ трогаем» |
| Embedding | `ADOPTED`=0, `BUILD_START`=0, `graph_facts_vec` gen1 `active` (fp `96f80838f683e1cb`), счётчики не изменились |
| ΔDDL | **0**, `user_version` **37** до и после |
| Style | `style.policy` rev 12 без изменений, `hint_limits` отсутствует, dash-фабрика не менялась |
| B11 | `ok=7, attention=2, unknown=1` |
| Откат | предыдущий прод `724b77ac` (2.58.117); дерево-откат `e9f7595b` (2.58.114) остаётся схемно-совместимым (ΔDDL=0) |

### Carry-over доказательств

Каждая запись evidence переведена на нового кандидата: `candidate_commit` = `9ed68ee8…`,
`produced_on` = новый кандидат, исходная привязка сохранена в `produced_on_original`,
в `observation` добавлена пометка `carry-over REL-258118` с основанием (каноны/fingerprint/данные
не изменились, гарды поезда перепрогнаны: `pins24 868/0`, parity 13, inspector 17, `llm_client` 115,
asap3 limits 16, hint e2e 10, e2e 142/0, W4 0).
Ссылки на артефакты `release-258117/*` перецелены на существующие файлы `release-258118/*`
(5 записей); `artifact_sha256` пересчитан там, где содержимое артефакта относится к текущему
кандидату — каждый такой пересчёт отмечен в `observation`.

## 2. Что закрыто в этом прогоне (только по существующим доказательствам)

### ASAP-SPEECH (`plans/features/asap-speech-arch/requirements-map.json`)

`INS-TRACE`, `INS-EXACT`, `INS-SKIPREASON`, `INS-HIERARCHY`, `INS-CONFLICT`, `INS-PRIVACY` →
**VERIFIED** (`live_required: false`, уровень preprod). Основание: прогон поезда
`release-258118/e2e-inspector.txt` — `checks=142 failures=0` на 7 viewport (320x720, 360x780,
390x844, 430x932, 667x375 landscape, 1280x900, 1440x900), плюс `evidence/inspector-exact.md` и
`evidence/r3/review.md`.

Что именно утверждает e2e (`tests/ui_inspector_exact_e2e.py`): метка «фактический запрос» и
checksum = sha256 отправленного payload; `system` совпадает; причина пропуска слоя по-русски, а
машинный код — в `title`; карточка конфликтов; иерархия ≥3 строк с раскрытием
текста/источника/редакции; в DOM нет секрета и полного Telegram-ID; нет обрезки текста и второй
горизонтальной прокрутки.
Ограничение честно: e2e идёт на синтетическом payload внутри UI-слоя, а не на реальном проде —
это preprod-доказательство, не live.

### ASAP3 (`plans/features/asap3-corrective/requirements-map.json`)

`HID-SCOPE`, `HID-AUDIT-PROMPTS`, `HID-AUDIT-INSTR-EXAMPLES`, `HID-AUDIT-CONTEXT-RULES`,
`HID-AUDIT-USER-EDITIONS`, `HID-AUDIT-MEMORY`, `HID-AUDIT-LENGTH`, `HID-AUDIT-OTHER`,
`HID-FIELDS-6` (все 6 вхождений), `HID-DELIVERABLE`, `HID-TECH-VISIBLE` → **VERIFIED**.
Основание: `evidence/limits-inventory.md` — 23 ограничения с `file:line`, шесть полей на каждую
строку (включая «могло терять молча» и «где показывать»), 4/4 `HIDDEN_LOSS` исправлены
(№11 текущий вопрос, №12 досье, №13 примеры регистра, №19 tail экстрактора), №14 закрыт как
defense-in-depth (`422` в UI) с WARN.

## 3. Гейт `requirements_gate.py check --stage release`

Команда по каждой карте:
`check --map <map> --stage release --candidate 9ed68ee8ab2b874d45832e57bed2deaa5d5b76b7 --deployed-commit <тот же> --repo .`

| Карта | scoped (обязательных) | errors | EXIT |
|---|---|---|---|
| asap-speech-arch | 115 | 23 | **1** |
| asap3-corrective | 234 | 30 | **1** |
| asap2-direct-chat | 110 | 10 | **1** |

Все ошибки — **только** `mandatory not ['VERIFIED']` (остаточные статусы, см. §4). Структурных
ошибок нет: инвентаризация источника построчно совпадает (`source_line`/`source_text_sha256`/
`source_excerpt`), `slice-graph` без циклов и перекрытий write-scope, у каждой VERIFIED-строки есть
candidate-bound evidence с существующим в репозитории артефактом, Git-объекты существуют локально.
Гейт **не** переводится в PASS и не ослабляется: остаток реален.

## 4. Остаток с классами (63 обязательных строки)

### ASAP-SPEECH — 23

| Класс | Строки | Почему не закрыто |
|---|---|---|
| WAITING_EXTERNAL (postdeploy) | `INIT-48H`, `EVAL-EGRESS`, `REQ-PROOF-EFFECT` (owner_optional) | после выката 2.58.118 реальных ответов бота не было; live-пробы в чаты не отправлялись без отдельной авторизации. `INIT-48H`: окно заново с рестарта `2026-10-23T17:51:27Z`, первое полезное наблюдение не ранее `2026-10-25 17:51 UTC` (26.10 05:51 UTC+12) |
| PENDING_AGENT_CHECK (Builder/Reviewer) | `T-UI-MATRIX`, `T-UI-TEXT`, `T-UI-STATE`, `T-GLASS-PERF` | e2e 142/0 покрывает 7 viewport, но **не** покрывает Windows fullscreen и Telegram-WebView UA 390; равенство после hard reload в новом процессе не показано; FPS Liquid Glass до/после не измерялся (`w4/report.md:262`) |
| PENDING_AGENT_CHECK (Builder) | `MIGR-CACHE`, `MIGR-VERIFY`, `T-PREVIEW`, `EVAL-MODES`, `P0D-QUOTED`, `ADD-EXPR-INTENSITY`, `T-I-COVERAGE`, `REQ-SCOPE`, `REQ-EMBED`, `REQ-PREFIX-SEP` | нужны отдельные прогоны/матрицы: полная 3×3×10 eval, quoted-мат, инвалидация кешей живым изменением, preview=build |
| NEEDS_IMPLEMENTATION (Architect) | `ARCH-ADR`, `TRACE-GRAPH` | ADR «почему L2 сохранён» и вызовный граф до provider API / Telegram `sendMessage` как отдельные документы отсутствуют |
| PENDING (Reviewer) | `ANTIPATTERN-MATRIX` | нет evidence-матрицы §4 (антипример → проверка) |
| REPORT-GATED | `REP-FORMAT`, `REP-NOFAKE`, `GOV-PENDINGLIVE`, `DOD-FINAL` | проверяются на финальном отчёте, не раньше |

`T-UI-GLASS` в карте отсутствует; ближайшее требование — `T-GLASS-PERF` (P2), оно осталось PENDING.

### ASAP3 — 30

| Класс | Строки | Почему не закрыто |
|---|---|---|
| READY_FOR_LIVE (postdeploy) | `ACC-03`, `ACC-09`, `A16` | после выката не было ни одного реального исходящего сообщения; `GET /api/speech/style` без TMA-подписи не вызывался. На release-стадии RFL законно не принимается |
| REPORT-GATED | `REPORT-CAUSE`, `REPORT-FIXED-MECHS`, `REPORT-LIMITS`, `REPORT-ALIAS-RULES`, `REPORT-LIVE-APPLY-PROOF`, `REPORT-VERIFIED`, `REPORT-REMAINING`, `REPORT-FORMAT`, `GOV-ROOT-CAUSE` | по указанию ждут финального отчёта |
| PENDING_AGENT_CHECK | `HID-NO-BUDGET-BREAK` (нет замера бюджета vs baseline), `HID-NO-BULK-OFF` (нет сверки защитных ключей до/после), `MIG-SCOPES` (нет read-only SELECT по трём уровням) | измеримые проверки, не выполнялись |
| PENDING — дизайн/UI | `HID-USER-SETTINGS`, `HID-NO-GLOBAL-EDITOR` | счётчики/настройки досье и примеров регистра в UI — отдельная полоса (inventory §1 «Где показывать»: «будущий счётчик») |
| PENDING — Reviewer | `GOV-NO-NEW-LLM` (счётчик LLM-вызовов не сверялся с baseline), `GOV-KEEP-SAFETY-LIMITS`, `GOV-NO-SIMPLIFY`, `AUD-PROD-VERIFY`, `AUD-REUSE-MAP`, `DASH-READABILITY`, `GOV-CORE-PRINCIPLE` | процессные/аудит-обязательства |
| PENDING — процессные роли | `GOV-ROLES-PM-ARCH`, `GOV-ROLES-BUILDER`, `GOV-ROLES-REVIEWER`, `GOV-ROLES-DEVOPS`, `GOV-NO-BLOCKING-GATE`, `GOV-QUEUE-INTEGRATION` | закрываются вердиктами/регистрацией, а не диффом |

### ASAP2 — 10

`DONE-D6`, `MIGR-PAYLOAD`, `MIGR-HOTAPPLY`, `DONE-D8`, `TESTS-METHOD-REAL`, `CLAR-L1-DIST4`,
`DONE-D1`, `DONE-D5`, `CLAR-L1-CONTINUATION`, `DONE-REPORT` — все PENDING с обновлённым `next_check`:
- `DONE-D6` — `WAITING_EXTERNAL`: первое реальное сообщение на 2.58.118 → снять `plan_meta needs_clar/clar_target_present`. Данные телеметрии не выдумывались.
- `MIGR-PAYLOAD`/`MIGR-HOTAPPLY` — нужен один допустимый тестовый маршрут (снимок payload без секретов; цикл save→next turn).
- `TESTS-METHOD-REAL`/`DONE-D8` — остаток T24 (ответ после рестарта) + Reviewer-подтверждение набора #19–#24.
- `CLAR-L1-DIST4`/`DONE-D1` — двухходовые парафразы на реальной модели.
- `DONE-REPORT` — финальный отчёт.

## 5. Прод и откат

- Прод работает на `2.58.118`; карты меняют только документацию, рантайм не затрагивается.
- Откат: `git checkout 724b77ac && sudo systemctl restart admin_bot` (предыдущий выкат),
  схема БД совместима (`user_version` 37, ΔDDL=0). Runbook канонов — `asap-speech-arch/evidence/r3b/rollback.md`.

## 6. Что это НЕ доказывает

Carry-over опирается на неизменность канонов/fingerprint/данных и на повторный прогон гардов
поезда; он не означает перепроверку старых доказательств на изменённом коде. Живое поведение на
реальном трафике (RFL-строки, 48-часовое окно, egress) остаётся неподтверждённым до первого
реального сообщения на 2.58.118.
