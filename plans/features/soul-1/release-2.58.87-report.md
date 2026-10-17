# Мини-релиз **2.58.87** — REL-25887 (fix-линия `release/fix-2.58.87`)

Дата: 2026-10-17/18 (UTC: деплой 22:49–23:01Z; локально 18.10.2026).
Статус: **задеплоен и живьём подтверждён** (healthz `2.58.87`, NRestarts=0);
Live-строки карт не закрывались (леджер — отдельный проход).

## 1. Состав (изоляция)

| Роль | Значение |
|---|---|
| База (прод до релиза) | `eafbe2e7b792c74eeb91735e183b767c6b85d73c` = 2.58.86, все оси ON |
| Порт-коммит (4 файла) | `f19b514a…` — `git checkout` отревьюенных кандидатов |
| Bump-коммит (31 файл) | `82e110d6…` — **деплой-тип** (prod HEAD) |
| Артефакты (этот коммит) | отчёт + `evidence/release-25887/**` |
| Delta vs прод | **35 файлов** = fix 4 (app.css + js-тест + style_policy.py + py-тест) + bump 31 (settings/README/F8-meta/24 py-пина/4 JS-пина) |
| UNCLASSIFIED | **0** (`isolation-classification.txt`) |
| WG byte-equal | fullscreen-policy/glass-refraction/glass-probe/refraction-тесты/e2e-инструмент — **байт-в-байт** (`wg-byte-equal.txt`) |
| SOUL-набор | byte-equal проду, кроме двух фикс-файлов (`soul-byte-equal.txt`) |
| Ревью-кандидаты | `7d3f0ca6` (master, REV-DROPDOWN-WG Approved `4b4ba983`); `68cd05b2` (REV-STYLE-AWAIT Approved `c6644f84`); файлы == кандидатам byte-exact (`equivalence.txt`) |

sha256_12 деплой-файлов (сверены и локально, и на проде): app.css
`d700df753d6d` · js-тест `62f7c2c4b167` · style_policy.py `f5eff9607d15` ·
py-тест `bcdbfc6465eb`.

## 2. Preflight (точное дерево ветки, логи в `preflight-*`)

| Проверка | Результат |
|---|---|
| `tests/test_soul1_style_policy.py` | **61 passed** |
| `tests/test_soul1_*.py` (30 файлов) | **600 passed** |
| parity (`test_soul1_composer_parity_off.py`) | **13 passed** |
| registry `--check` | **CHECK OK: 575 == REGISTRY** |
| node guards | **87/87** (`preflight-node-guards.txt`) |
| зуб U02.4 (A/B) | base `eafbe2e7` → **RED** (`AssertionError U02.4`) / ветка → **GREEN** (`W2-SHELL-UNIT-OK`) |
| refraction e2e | **37/37, WG-REFRACT-E2E-OK** |
| shell e2e | **W2-SHELL-E2E-OK**, `failed_checks {}`, `console_errors []` |
| fs e2e | **12/12 PASS (166 чеков)** |
| frozen-check | **RESULT OK** (в т.ч. новый маркер `oversight-dd-open` PRESENT) |

## 3. Деплой (1 recon + 1 main SSH-коннект; `deploy-run.txt`, `recon.txt`)

- A: прод до = `eafbe2e7` / `release/soul1-2.58.86` / healthz 2.58.86 /
  TRACKED_MOD=0 / `.env` оси 5/5 ON.
- B/C: fetch+checkout `release/fix-2.58.87`; `DELTA_FILES=35`;
  NEW_HEAD=`82e110d6…`; TRACKED_MOD_AFTER=0.
- D: **17/17 sha256_12 == кандидатам**; markers: `APP_VERSION = "2.58.87"`,
  `DD_OPEN=2`, `DD_OVERFLOW=1`, SOUL-файлы present.
- F: graceful-рестарт; миграции: `start | user_version=36 | pending=[]` →
  `complete | user_version=36 | 0.0s` (новый PID); **healthz 2.58.87** (loopback
  + HTTPS); журнал ERROR/CRITICAL/Traceback = **0**.
- J: `/web/static/app.css` на проде: sha12 **`d700df753d6d`** (и по HTTP),
  `oversight-dd-open`×2, `overflow: visible !important`×1; PAGE_VER ok;
  service: ActiveState=active, **NRestarts=0**, ExecMainStatus=0.

## 4. Живые пост-проверки (`post-check.txt`, `final-verification.txt`)

**(а) Глобальное сохранение стиля (цель релиза, дефект await):**
PG `style.policy` **отсутствовал** → `POST /api/speech/style` (scope=global,
пустой фабрично-равный документ) → `applied=true, revision=1` → PG `style.policy`
**появился** (rev 1) → второй save → **rev 2** (растёт) → `GET /api/speech/style`:
`source=global`, `global_present=true`, `inheritance=global`. Журнал:
`[style_policy] document saved | scope=global | revision=1|2` ×2; 
**RuntimeWarning/«never awaited» = 0** за всю сессию после рестарта. Дефект
2.58.86 закрыт живым доказательством.

**(б) F5 досчёт (ревью-нит REV-REL-SOUL):** SELECT **всех 50** `persona_traits`
→ маркер-скан. Итог честно: **1 маркер** — `id=245` (chat −1002661910336,
`source=deep_sleep`), термин «двач»; base-маркеры (токсичность) = 0.
Классификация: EXT-термин «двач» санкционирован каноном SOUL-1
(`l2_dvach_vocabulary`); это живой трейт (данные владельца), не продуктовый
дефект; зафиксирован для видимости леджера. Остальные 49 — чистые.

**(в) Оси SOUL:** gates **10/10 ON** (`unified_composer, character_core,
speech_style_policy, humor_library, humor_feedback, experience_lessons,
smart_verbalizer_modes, response_plan, persona, character_layers`);
withheld=11 (как в 2.58.86); `.env` 5/5 осей на месте; оси не трогались.

**(г) Dropdown (мобильный) на проде:** app.css отдаётся с маркером и
sha==кандидату (побайтова эквивалентность с отревьюенными байтами); тот же
CSS-файл проходит shell-e2e (hit-тест `elementFromPoint` = кнопка опции,
тап → `?tab=memory`) в локальном harness на прод-байтах. **Живой hit-тест на
origin — owner-check**: страница вне Telegram открывает auth-гейт (скриншоты
`smoke-prod-390*.png`), экран аналитики не рендерится без initData.

**(д) Журнал:** ERR=0; WITHHELD=11; GRACEFUL=2; POLLER=1; `style_policy saved`
×2; HTTPS healthz 2.58.87, /web/ 200.

## 5. Rollback

`release/soul1-2.58.86` + graceful-рестарт (оси не трогаются; авто-откат в
скрипте не потребовался — healthz 2.58.87 получен). Проверка способности
отката — штатный `R1–R3` путь скрипта (не исполнялся по ненадобности).

## 6. Девиации (честно)

1. **T0-баг деплой-скрипта:** `%%`-экранирование в `F2_restart` — timestamp
   рестарта не подставился; F3_migration_wait (PID-анкер) и журнальные срезы
   первого прогона журнала вакуумны; F3 отработал полные 600с ожидания
   (healthz проверен отдельно и ок). Первый артефакт сохранён
   (`final-verification-firstrun-vacuous-journal.txt`), журнальные проверки
   **перепроведены** read-only прогоном с точным таймстампом
   (`final-verification.txt`) — см. §4. Сам hardening F3 (PID-анкер вместо
   `--since -12min`) реализован в `soul87_f3.sh`.
2. **F5:** 1 маркер (см. §4б) — типовая находка живой персоны, не блокер.
3. **Живой hit-тест dropdown** — owner-check (auth-гейт), см. §4г.
4. Экран «Стиль письма»: глобальный документ теперь персистится и **пуст**
   (семантика == заводская, правил владельца не выдумано) — ревизии 1–2 в PG.

## 7. Ledger

| Пункт | Статус |
|---|---|
| 1. Изоляция 35=4+31, 0 некласс., WG/SOUL byte-equal | VERIFIED (скрипт + гейт) |
| 2. Preflight 61/600/13/575/87/37/OK/12·166/frozen OK + зуб A/B | VERIFIED |
| 3. Деплой: HEAD/hashes/markers/healthz 2.58.87/ERROR=0 | VERIFIED |
| 4. style global save: PG rev1→rev2, RuntimeWarning=0 | VERIFIED (live) |
| 5. F5 50/50 traits | VERIFIED (1 маркер зафиксирован) |
| 6. Оси 10/10 ON | VERIFIED (live) |
| 7. Dropdown на проде (bytes+harness) / живой тап | VERIFIED / owner-check |
| 8. Журнал ERR=0, withheld 11 | VERIFIED (повторный прогон) |
