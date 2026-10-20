# REV-REL-258101 — независимое ревью релиз-поезда 2.58.101 (07A-2 каноны + бамп)

- **Ревьюер:** REV-REL-258101 (parent Reviewer, read-only + evidence). Дата: 21.10.2026.
- **Кандидат (поезд):** `3b83da92486a3149d1094f6e48ce2ef93abdd9e2` (HEAD master), прод-базис 2.58.100 `acc285d7` = предок (`git merge-base --is-ancestor`, exit 0).
- **Вердикт: Needs Fixes — 1 книжный блокер (CFG-07A.1 → READY_FOR_LIVE). Код поезда проверен полностью и НЕ требует переработки; после одного docs-коммита — push+deploy без повторного код-ревью.**

## 1. Проверено независимо (все на HEAD поезда)

| # | Проверка | Результат |
|---|---|---|
| 1 | `git show 211a8c1b --stat` vs review-07a2 §8 | 33 файла = ровно 12 services + 14 tests + 1 контракт-тест + 2 канон-доки + 4 evidence; родитель `476e11a5` (база ревью); чужих файлов нет — СОВПАДАЕТ |
| 2 | Байт-сверка PREV_*_CFG07A (HEAD) == активные каноны acc285d7 | **7/7 OK**, хэши = записанным в review-07a2 §1 (direct 0b853c37, summary 4820a270, checkup 0ce06cb1, search 5950206a, youtube dd57d213, youtube_video 47e304d8, web c384282d); метод: `git archive acc285d7 services+config` → раздельные импорты старого/нового деревьев с маркер-чеком `__file__` |
| 3 | Fingerprint | `factory_set_fingerprint()` = `037080375ac8` == `FACTORY_SET_SHA256_12` (независимый прогон) |
| 4 | c849dbf4 (06G.3, уже в проде 2.58.100) | 8 файлов зоны; mca17c 301→302 применён ровно как B1 review-06g3 (вердикт того ревью «Needs Fixes — 1 блокер», фикс в коммите); `factcheck_prompts.py` вне 8 файлов; `git diff acc285d7 HEAD -- services/factcheck_prompts.py` пуст (W3-фриз цел) |
| 5 | Бамп 3b83da92 | 31 файл, +33/−33; нормализация только 3 токенов (2.58.100, 2\.58\.100, 27b1165a) → **0 unmatched строк**; F8-meta HEAD=`211a8c1b` (по прецеденту 98–100 — кодовая линия); settings APP_VERSION=2.58.101 |
| 6 | F8 `gen_param_registry_round1025.py --check` | `CHECK OK: реестр 582 == REGISTRY`, exit 0 |
| 7 | Тесты на HEAD | контракт `test_cfg07_backstage_contract.py` **59p** (включая test_positive_controls_alive — отдельного файла нет, N/A); route-coverage **18** + mca17c **8** = 26p (сборки подтверждены по отдельности) |
| 8 | ΔDDL | `git diff acc285d7 HEAD -- services/database.py scripts/` пуст; `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` неизменна; v37 остаётся с 2.58.100 |
| 9 | Откат | PREV-лестница: `bot.py:1368` вызывает `migrate_prompt_canons` на старте; `rollback_prompt_canons` (prompt_migrations.py:406) — прод-откат без git; лестницы узнают прод-байты (п.2, 7/7) + контракт-тесты 59p; рубеж `release/fix-2.58.100`=`acc285d7` создаётся при push (прецедент `release/fix-2.58.99`=`7142ffcf` существует) |
| 10 | requirements_gate | `--stage plan` EXIT 0; `--stage review --slice CFG-07A --candidate 211a8c1b` EXIT 1 (6 ошибок — классификация в §2) |

## 2. Классификация ошибок гейта `--stage review` (EXIT 1, errors=6)

- **CFG-07A.1** (live_when=postdeploy, обязательная) — статус PENDING. Постдеплой-only: эффективный пейлоад-трейс возможен только после деплоя этого кандидата. По семантике гейта и регламенту на этапе review единственный честный статус — **READY_FOR_LIVE** (прецедент cc7ac8d7: постдеплой-строки → VERIFIED @ deployed уже после канарейки). **ЕДИНСТВЕННЫЙ блокер поезда** — книжный: 1 JSON-статус + evidence, привязанный к `211a8c1b` (артефакт уже в репо: `07a2-summary.md` §2, план 07A-1.final).
- **CFG-07A.3, CFG-07A.5, CFG-07D.1, CFG-07D.2, CFG-07A.F** — будущие волны 07C-G в скоупе слайса (review-07a2 §9: «это план, не дефект»). НЕ долг этого поезда; слайс CFG-07A легитимно остаётся открытым до 07C-G. Поезд не заявляет DONE слайса/фичи.

## 3. Acceptance-леджер поезда

- VERIFIED (на кандидате 211a8c1b, независимо): периметр коммита, байт-паритет лестниц 7/7, fingerprint 037080375ac8, F8 582==REGISTRY, 59p+18+8 тестов, ΔDDL=0, бамп 33/33 пар, settings import 2.58.101, W3-фриз фактчека, rollback-механизм, честный леджер 5 VERIFIED.
- READY_FOR_LIVE-класс (после деплоя): CFG-07A.1 effective-payload трасса; опциональное владельческое наблюдение метатекста (plans/owner_live_checks.md §2/§7, не-блокер по standing rule 18.10.2026); `--stage release` после деплоя.
- Родитель CFG: НЕ DONE (07C-G + 07A.1.final открыты) — план, не дефект.

## 4. Чужие остатки в дереве (не влияют на кандидата)

6 tracked-modified: workflow_state.md, asap8-v6-3 (map/reconciliation/requirements-map), cfg-06 w7-dispute-metrics, archive mca-17c evidence, samples-ux map (deployed_commit=acc285d7 — книжка 2.58.100). Untracked: node_modules/package*, .playwright-mcp, _upd.py, OPENCODE_WORKFLOW_SCRATCH, verification_cache.json, evidence-каталоги. Ни один не входит в поезд; behavior не задевают.

## 5. Минимальное исправление (до push)

1. Коммит docs-only: в `plans/features/cfg/requirements-map.json` строка CFG-07A.1 → `"status": "READY_FOR_LIVE"` + evidence `{candidate_commit: 211a8c1b…, type: plan, ref: plans/features/cfg/evidence/cfg-07a/07a2-summary.md, observation: постдеплой-трасса 07A-1.final по §2, rollback — PREV-лестница}`. В этот же коммит — каталог `plans/features/cfg/evidence/cfg-07a/release/` (README, гварды, review-rel.md).
2. Речек: `requirements_gate.py check --map plans/features/cfg/requirements-map.json --stage review --slice CFG-07A --candidate 211a8c1b…` → ожидаемо errors=5 (только 07C-G-строки, класс открыто-плановых). Код не меняется, тесты не перегоняются.

## 6. Команды push/deploy (после п.5)

```bash
git push origin master
git push origin acc285d77d03c7adbf5527dc7f0fa9e9904fed8e:refs/heads/release/fix-2.58.100   # рубеж отката
# деплой: строго по deploy_commands.txt (креды не печатать), fail2ban-дисциплина:
#   1 recon-коннект ~15с; порт закрыт -> пауза >=22мин (прод жив по HTTP);
#   один основной коннект: выкатить дерево поезда, рестарт сервиса
curl -s https://admin-bot.duckdns.org/healthz    # до: 2.58.100 -> после: 2.58.101
```

Постдеплой: healthz 2.58.101; логи/публикации; CFG-07A.1 трасса → VERIFIED @ deployed-sha; наблюдение метатекста — владельцу опционально; `--stage release`; ledger-коммит + push evidence.
