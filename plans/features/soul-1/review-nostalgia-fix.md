# REVIEW-NOSTALGIA-FIX — независимое ревью восстановления ностальгии (P0-followup §2)

| Поле | Значение |
|---|---|
| Кандидат | uncommitted-правки поверх `2c916f35` (в рабочем дереве HEAD = `185cff1c` docs-коммит поверх базы); sha256_12 всех 10 файлов лейна сверены и **совпали** (`da8c9b79e9cf`/`26b8e73ece03`/`1708a1425605`/`0fc58b110fcc`/`5c5bef03d4b2`/`d11ea9c010bb`/`92c304ae50d8`/`4e28a5254e88`/`1e2bf44d179b`/`21625eae27c2`; конвенция — sha256 файла, не git-object) |
| Baseline | мои чистые worktree на `2c916f35` (scratch) |
| Вердикт | **Approved** — блокеры закрыты корректно, канон/паритет/единый контур подтверждены; остаётся только post-deploy живой остаток (§7) и два хвоста-находки (§6, не блокеры) |

## 1. Блокеры — соответствие вердиктам (код + прод-лог)

* **#3 (главный) — ПОДТВЕРЖДЁН прод-данными и закрыт.** `prod-readonly-2026-10-18.txt`: **каждый** тик за 30 дн по чату `-1002661910336` = `reason=silence_too_short` (28 строк журнала), чат сверхактивен (2 026 184 сообщения, последнее — за минуты до probe), кандидатов «год назад» — **26 738**; `nostalgia_log`: `sent=2` за всю историю. Фикс снимает требование тишины **только для сценария A**: `active = last_ts + silence_min > now` → A (живая беседа) минует гейты тишины и quiet hours; B (затишье) сохраняет quiet hours/тишину (контрольный тест `test_scenario_b_quiet_hours_still_skip` зелёный на RED — единственный pass). Cooldown 12ч/лимит 3/сутки/Q14/порог/budget в A сохранены (код: гейты 4–6 после классификации, не изменялись).
* **#1 — ПОДТВЕРЖДЁН (механизм, латентный) и закрыт.** `start()` теперь регистрирует джоб **всегда** (`replace_existing`-идемпотентность), единственный вызов — `bot.py:760` (grep: иных точек регистрации нет); OFF → дешёвый no-op тика + честное событие `nostalgia_run skipped/disabled` (`_nostalgia_terminal(enabled=False)`); `run_once` режется kill-switch (no-op путь; тесты). Паттерн сверен с DreamWorker (`start()` документирует «регистрируются ВСЕГДА … переключение тумблера действует без рестарта») — тот же замысел, реализация аккуратная.
* **#2 — ПОДТВЕРЖДЁН:** `settings.NOSTALGIA_ENABLED` default `False` (settings.py:3214), в проде env-ключа нет, включение — hot PG (`memory.nostalgia_enabled=true`), т.е. ось включения теперь работает без рестарта.
* **#4/#5 — класс «НЕ ПОДТВЕРЖДЁН как блокер» честен:** в `nostalgia_log` нет строк cooldown/threshold/max_per_day; 209 `budget_skip` — это per-chat `gate_nostalgia` **второго** чата (`-1004482340693`), не budget; `initiative_*` строк нет (делегирование в проде не запускалось — кандидаты не доходили). Возможный `initiative_*`-silent — штатный mca-10b (общий механизм Decision), не второй контур; наш путь различим (`source=nostalgia`, `trigger_kind=nostalgia_due`, `prepared_text_ref=nostalgia:*`), закреплено тест-спаем.

## 2. A/B-логика (код + тесты)

Критерий — свежесть последнего юзерского сообщения; A: без тишины и quiet hours; B: прежние гейты; общие анти-навязчивость (cooldown 12 ч, max 3/сутки, Q14-стоп, порог `0.3+0.5*aggr=0.45`, budget) и `is_active`/`chat_id<0`. User-блок A: «В чате сейчас живая беседа. Вот память:» (тест), B — прежний «В чате давно тихо». Мой прогон ключевой тройки на кандидате: **43 passed**; AB-файл (8 контрактов: hot-enable, A-отправка, A+quiet hours, B-контроль, no_candidates/unchanged, канон-сосуществование, делегирование) — зелёный.

## 3. Канон — ON без legacy-персоны, OFF байт-в-байт

* `NOSTALGIA_CORE_CANON`: формат/«UNCHANGED» сохранены, тонально-личные утверждения («токсично-тёплый», «ленивая печать», «робот-архивариус») убраны — диффом показано.
* **OFF-паритет (мой независимый замер):** `NOSTALGIA_PROMPT` base↔candidate **байт-идентичен** (sha256 `7631bbcc…`); OFF-system == legacy_canon (`bytes_equal_legacy_canon: True` в дампе); user-блок OFF (default `active=False`) — одинаковый хэш на базе и кандидате (`2d687e49c5a83a9e`), голова «В чате давно тихо. Вот память:».
* Артефакт `system-prompt-on-vs-off.txt` **воспроизведён мной** тем же скриптом: содержимое совпало (3009 == 3009). ON: genre-рамка + Core + UNCHANGED, без legacy-маркеров; делегированный кандидат — `source=nostalgia`/`nostalgia_due`/`nostalgia:year_back`. Legacy не возвращается активным слоем (он только OFF-путь, как и было).

## 4. Единый контур/дедуп

`_delegate_initiative` → `direct_chat_service.handle_initiative` (K1+K3) с `source=nostalgia`, `trigger_kind=nostalgia_due`, `prepared_text_ref=nostalgia:*`; ошибка делегирования — честный `error` **без** legacy-фолбэка (второй send-path не создаётся). Тест-спай фиксирует поля + `nostalgia_log meta.path=initiative`. Legacy-ветка (`bot.send_message`, вне делегирования) — прежний, не второй контур.

## 5. RED→GREEN (мои прогоны) + флейки-классификация

* **RED — воспроизведён точно:** base-worktree `2c916f35` + тесты лейна → **9 failed / 1 passed**, тот же состав (включая `test_flag_off_job_registered_and_run_once_skipped` и w4-`core_canon`); единственный pass — контроль B.
* **GREEN:** та же тройка на кандидате → 10/10; ключевые 3 файла → **43 passed**; 20-файловый набор (nostalgia/soul1-W4/mca17/mca09-b/d/e/off-parity/feature_gates/webapp-memory/каталог/freeze/registry) — кандидат **320 passed**, lane-only worktree **320 passed**; `gen_param_registry_round1025 --check` → **OK (575 == REGISTRY)**.
* **Broad-фильтр** `-k "soul1 or nostalgia or authorial or param_catalog or prompt_registry"` → мой чистый прогон **766 passed** (сходится с логом лейна), но 2 из 4 прогонов дали 1–2 падения в **разных** тестах (в т.ч. в чужом `test_mca09_intents_block_e…` и в `test_nostalgia_worker.py`), все — зелёные standalone. **Классификация: пре-существующая флейки широких прогонов** — воспроизведена мной на **чистой базе** `2c916f35` (broad ×2: по 1 падению в разных тестах; 19-файловый набор ×3: падение в x2, разные). Не от лейна; гигиена-нить (в отчёте лейна «766 passed» — значение чистого прогона, не инвариант).

## 6. Находки (не блокеры)

1. **UI-правдивость:** `web/api/memory_agi.py::_nostalgia_state` отдаёт `mode='silence'` при свежем юзерском сообщении, `app.js::nostalgiaLabel` рисует «Тишина: N/45 мин» — после A/B метка вводит в заблуждение (вспоминание уже возможно). Решение для UI-волны: добавить поле `active`/`scenario` и лейбл «Живая беседа — вспомнит, если уместно».
2. **ARCHITECTURE §2c (стр. ~332)** описывает тишину как безусловный гейт — устарело после A/B (док-фикс; уже помечено хвостовым артефактом).
3. **`bot_replied_recently=False`** (дефолт `InitiativeSituation`): в решении (`mca_intents.py:376`) `True` → `wrong_moment`/silent; с дефолтом ностальгия может уйти сразу после реплики бота (защита — cooldown/лимиты/Q14). Оговорка README «нет дешёвого источника» неточна: для direct-чатов источник есть (`direct_chat_service._bot_replied_recently` + окно) → в backlog, риск низкий.

## 7. Решения для леджера (что закрываем, что остаётся live)

* **Закрыть (код+тесты, pre-deploy):** `P0B-NOST-RESTORE` (§1), `P0B-NOST-SCEN-A/-B` (код-контракт A/B), `P0B-NOST-ONE-CONTOUR`, `P0B-SEPARATION` (артефакт ON/OFF + тест делегирования), description-фикс каталога + freeze re-pin (`L-F11S-1`, исторический fixture не тронут).
* **Live (post-deploy, заранее не засчитывать):** (1) journal `[nostalgia] scenario=A (живая беседа) | chat=-1002661910336 …`; (2) следующая строка воронки — `sent` c kind либо честная причина (`no_candidates`/`threshold`/`unchanged`/`budget_skip`/`initiative_*`); (3) новая строка `nostalgia_log` для этого чата; (4) `mca_events` `nostalgia_run` start+success; (5) per-chat gate второго чата `-1004482340693` — конфиг (`gates[nostalgia]=true`) при релизе, затем тот же прогон воронки. Выполняет DevOps/Orchestrator штатным post-deploy чеком (не owner-гейт; read-only проверки, fail2ban-дисциплина).

## Итог

Восстановление ностальгии подтверждено независимо: прод-диагноз (тишина резала каждую живую беседу) верен, A/B разделение корректно и не ослабляет анти-навязчивость, OFF-путь байт-в-байт прежний, Core-канон не конкурирует с SOUL-1, единый Decision переиспользован без второго send-path. Блокеров нет; хвосты §6 и живой остаток §7 не препятствуют релизу.
