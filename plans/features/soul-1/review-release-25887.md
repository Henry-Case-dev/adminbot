# SOUL-1 — REV-REL-25887: независимое ревью мини-релиза 2.58.87 (18.10.2026)

**Вердикт: Approved.** Изоляция/байты, preflight, живые факты await-фикса, T0-девиация и границы подтверждены независимо, включая мою живую проверку прод-байтов (read-only GET). Решения для леджера — §6; блокирующих находок нет.

## Привязка

| Поле | Значение |
|---|---|
| deployed (prod HEAD) | **`82e110d6`** (`release/fix-2.58.87`; healthz 2.58.87) |
| Порт | `f19b514a` — 4 файла (`git checkout` отревьюенных кандидатов) |
| Bump | `82e110d6` — 31 файл (settings/README/F8-meta/24 py-пина/4 JS-пина) |
| Tip/артефакты | `54a69f32` (31 файл: отчёт + 30 evidence; всё в `plans/features/soul-1/**`); `ls-remote origin` = tip |
| База/rollback | `eafbe2e7` (2.58.86, оси ON) |
| Мои прогоны | worktree `rev-rel-25887` @ `54a69f32` (runtime == `82e110d6`); read-only |

## 1. Изоляция/байты — VERIFIED

- Мой git-пересчёт дельты `eafbe2e7→82e110d6` = **35 файлов**; `isolation-classification.txt`: bump 31 + fix-await 2 + fix-dropdown 2, **UNCLASSIFIED=0**.
- `f19b514a` = ровно 4 файла; byte-exact vs отревьюенных: `git diff f19b514a 68cd05b2 -- services/style_policy.py tests/test_soul1_style_policy.py` = пусто; `git diff f19b514a 7d3f0ca6 -- web/static/app.css tests/js/asap8_w2_shell_mobile_nav_test.js` = пусто. Sha256_12 на `82e110d6`: `d700df753d6d`, `62f7c2c4b167`, `f5eff9607d15`, `bcdbfc6465eb` — совпали с отчётом.
- WG-артефакты byte-equal (6 путей; сходятся и по blob-префиксам, и по diff); SOUL-набор byte-equal, кроме двух фикс-файлов (`SOUL_BYTE_EQUAL_EXCEPT_FIXED=True`).
- **Моя живая проверка прод-байтов (независимо):** `GET /healthz` → 200 `{"status":"ok","version":"2.58.87"}`; `GET /web/static/app.css` → 200, sha256_12 **`d700df753d6d`** (== кандидату), маркеры `oversight-dd-open`×2, `overflow: visible !important`×1.
- Коммиты ветки на месте (`f19b514a→82e110d6→54a69f32`).

## 2. Preflight — VERIFIED (мой повтор, целевые)

| Проверка | Мой результат |
|---|---|
| `tests/test_soul1_style_policy.py` | **61 passed** |
| `tests/test_soul1_*.py` (30) | **600 passed** |
| registry `--check` | **575 OK** |
| parity (`test_soul1_composer_parity_off.py`) | **13 passed** |
| node `tests/js/*` | **87/87** |
| Зуб U02.4 A/B | base-линия (`d5191450`, runtime == `eafbe2e7`) + новый тест → **RED** `AssertionError: U02.4 …обрезается поверхностью рефракции`; релиз-ветка → **GREEN** (в составе 87/87) |
| refraction e2e | **37/37**, WG-REFRACT-E2E-OK |
| shell e2e | **W2-SHELL-E2E-OK**, `failed_checks {}`, `console_errors []` |
| fs e2e | **12/12 PASS** |
| frozen-check (ленсовский адаптер) | **RESULT OK**; новый маркер `oversight-dd-open` — **PRESENT** |

## 3. Живые факты (прод) — VERIFIED; полнота доказательства await-фикса

- `style.policy`: до — `global_present=false`; save1 → `applied rev=1` → PG-строка (23:00:23.089508) → `GET`: `source=global`, revision `g1.0483be84f90e`, `global_present=true`, `inheritance=global`; save2 → **rev=2** (…140741) — ревизии растут; журнал `[style_policy] document saved … revision=1|2`; **RuntimeWarning / «never awaited» = 0** (final-verification, срез «since T0» после сохранений). Дефект 2.58.86 закрыт по существу (персистентность + отсутствие предупреждения).
- **Оговорка о полноте:** сохранён пустой фабрично-равный документ — это доказывает именно сломанный механизм, но **не** поведенческую клаузу «реальные правила меняют следующую генерацию»; это отдельный шаг (см. §6а). Поэтому AMD.8.3 не переводится в VERIFIED.
- Оси: gates **10/10 ON**; withheld=**11** (список = классу удержания); журнал **ERR=0**; healthz 2.58.87 (loopback+HTTPS); `user_version=36`, миграции `complete 0.0s`.
- F5: **50/50** traits просканированы; **1 хит** `id=245` — текст владельческого deep-sleep-трейта («…идти на двач.»); base-маркеров 0, остальные 49 чистые. Честность: сам хит и класс «не продуктовый дефект / живые данные» — верно; формулировка отчёта «санкционирован каноном `l2_dvach_vocabulary`» **неточна** (это правило, наоборот, исключает двачерскую лексику из legacy L2-канона; слово «двач» здесь из владельческого наблюдения, не из канона) — рекомендованная пометка §6в.

## 4. Девиация T0 — VERIFIED (перепроверка легитимна)

- Первый срез сохранён (`final-verification-firstrun-vacuous-journal.txt`): `RESTART_T0=%Y-%m-%d %H:%M:%S`, `F3_T0=` пусто, F3 604.2 s (60 итераций), журнальные проверки пусты (WITHHELD=0/GRACEFUL=0) — `%%`-экранирование сломало подстановку таймстампа.
- Перепроведение (`final-verification.txt`, read-only, 23:01:10Z): срез «since T0» даёт реальные строки — миграции 22:50:29, ERR=0/RUNTIMEWARN=0/WITHHELD=11/GRACEFUL=2/POLLER=1, сохранения 23:00:23; таймстампы старше проверки и совпадают с deploy (рестарт 22:50:08) и post-check — **не «подогнано»**; прод-следов нет (`NRestarts=0`, `TRACKED_MOD=0`, HEAD/ветка корректны).
- Hardening `soul87_f3.sh` (PID-анкер: `python[$MainPID]` + `migrations: complete` since T0) — адекватен против нита «старая строка журнала» (тот же класс, что в REV-REL-SOUL §6), но сам **T0 в каноническом деплой-скрипте по-прежнему генерируется с `%%`-багом** → follow-up §6г.

## 5. Границы — VERIFIED

- Живой тап dropdown на origin: вне Telegram — auth-гейт (подтверждено просмотром `smoke-prod-390-oversight-playwright.png` и живой отдачей байтов) → **owner-check**; пометка легитимна; harness-эквивалент (shell-e2e hit-тест на прод-байтах, `?tab=memory`) — зелёный.
- Карты на ветке не тронуты (`git diff eafbe2e7 54a69f32 -- requirements-map*.json` = пусто); tip-коммит — только отчёт + evidence (31 файл).

## 6. Решения для леджера

- **(а) style-строки.** `SOUL-AMD.8.3` — оставить **READY_FOR_LIVE**; добавить прод-эвиденс 2.58.87 (`post-check.txt` rev1→rev2 + `global_present`; `final-verification.txt` RUNTIMEWARN=0; моя живая проверка байтов) и освежить устаревшую формулировку «до канарейки (флаг ON — решение владельца)» — PET, канареек нет. VERIFIED — только после шага «реальное правило + наблюдение применения» (агент: save реального правила + `try`-hint в сборке; финально — живой ответ владельца). `SOUL-16.5.1/2/3` этим фиксом не закрываются (свои не-live пробелы: «История изменений» политики, доп. UX-чек, 10+ разнородных прогонов) — статусы не менять; save-путь разблокирован.
- **(б) Dropdown-фикс.** Привязать к `plans/features/asap8-v6-3-live-correction` — строки `REQ-U02`/`U02.2`–`U02.3` (их контракт ломался WG-слоем): добавить **регрессионную пометку** с trail (WG 2.58.85 → REV-DROPDOWN `4b4ba983` → коммиты `7d3f0ca6`/`f19b514a` → деплой 2.58.87 → shell-e2e/зуб/живые байты), статусы (уже VERIFIED) не переводить и не трогать; cross-ref в win-glass-леджер (первопричина — inline overflow/clip слоя рефракции). Живой тап — owner-check.
- **(в) F5-находка.** Закрыть нит в `SOUL-AMD.4.6`: «F5-досчёт 50/50 выполнен; 1 EXT-хит `id=245` — живой трейт владельца (не инструкция), base=0; остаётся как есть, не блокер» + поправить обоснование (не «санкционирован каноном», а «данные владельца; правило `l2_dvach_vocabulary` к находке не относится»).
- **(г) T0-hardening.** В канонический деплой-скрипт: (1) исправить подстановку T0 (`%%`-эффект), (2) fail-fast при пустом T0, (3) перенести PID-анкер `soul87_f3.sh` в канонический F3. Фиксация — `workflow_state.md`/заметка REL-лейну (не строка карты). Non-blocking: вред ограничен одним вакуумным срезом, перепроверенным read-only; healthz/миграции проверялись отдельно.

## Ledger

| Пункт | Статус |
|---|---|
| 1. Изоляция/байты (35=4+31, byte-exact ×4, WG/SOUL, живая отдача байтов) | VERIFIED |
| 2. Preflight (61/600/575/13/87/зуб/37/shell/12/frozen) | VERIFIED (мой повтор) |
| 3. Живые факты (style rev1→rev2, RW=0; gates; withheld 11; ERR=0; F5 50/50) | VERIFIED (F5 — с поправкой формулировки) |
| 4. T0-девиация (перепроверка легитимна; следов нет; hardening — с follow-up) | VERIFIED + §6г |
| 5. Границы (owner-check dropdown; карты не тронуты) | VERIFIED |
| 6. Решения для леджера | изложены (а–г) |

**Итог:** Approved; блокирующих находок нет; обязательны только леджерные шаги §6 (в плановом проходе, без нового релиза).
