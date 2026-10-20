# REV-REL-258102 — независимое релиз-ревью поезда 2.58.102 (F1 custom-clean + бамп)

Дата: 21.10.2026. Ревьюер: Reviewer (leaf REV-REL-258102), read-only + этот evidence-файл.
Кандидат: **`a3535b68a3220f5a239ed7df3eb1a24f1e1d0873`** (HEAD worktree сверён) поверх прод-базиса
2.58.101 `e3c61445` (предок подтверждён `merge-base --is-ancestor`). Коммиты поезда:
`e3fd364c` (docs: deploy-258101 evidence, 2 файла), `6388899d` (F1, 4 файла), `a3535b68` (бамп, 31 файл).
review-06g3/deploy-25899 уже на прод-линии (acc285d7 ⊂ e3c61445 — сверено).

## ВЕРДИКТ: **Approved** (push + deploy; постдеплой-речек → CFG-07A.1 VERIFIED @ deployed)

## Независимые проверки (выполнены ревьюером на кандидате)

1. **Гигиена поезда** — ПАСС. `git diff e3c61445..a3535b68 --stat` = 37 файлов: 4 F1 +
   31 бамп + 2 docs-evidence. samples-ux / фактчек-attribution / mca_sample_library /
   `database.py` — отсутствуют. Секрет-скан всех +723 строк (токены/bot-token/sk-/conn-str) —
   **0 попаданий**. 6 чужих dirty-файлов в дереве (plans-доки других лейнов) в поезд НЕ входят.
2. **F1 байт-равенство** — ПАСС. sha256_12 при `a3535b68`: prompt_registry `b28459d008a1`,
   prompt_factory `46cbcc0c0c8a`, test_cfg07a_f1_custom_suppress `c87b04784017`,
   test_soul1_registry_legacy_removal `a9a2e31a51aa` — все 4 == review-f1.md.
   Скоуп `CFG07A_PAYLOAD_CLEAN_KEYS` = ровно 7 ключей; known-canon-гейт консервативен
   (widening только `not known` × chat/global × 7 ключей); `prompt_migrations.py` вне диффа;
   `spec=None` → early-return «missing»; default-путь вне скоупа; записи в PG нет (0 set-calls).
3. **Бамп** — ПАСС. 33+/33−, каждая изменённая строка = пара версия/HEAD (программная сверка;
   8 «лишних» строк — это JS-регэкс `2\.58\.10x`, та же пара). README: 1 строка, длины равны,
   разница только `v2.58.101→v2.58.102`. settings import → **APP_VERSION 2.58.102** (проба).
   F8 `--check` **EXIT 0**, REGISTRY == **582** (прямой импорт). ΔDDL = **0**:
   `database.py` вне поезда, `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` не тронута (v37 остаётся).
4. **Прогоны на HEAD** — ПАСС. test_cfg07a_f1_custom_suppress + test_cfg07_backstage_contract
   = **110 passed** (51+59), route-coverage **18 passed**, `factory_set_fingerprint()`
   == **037080375ac8** (runtime-проба ревьюера).
5. **Rollback** — ПАСС (по конвенции + механика). Рубеж `release/fix-2.58.101` = `e3c61445`
   создаётся при push (прецедент `release/fix-2.58.100`=`acc285d7`, verified on prod при
   деплое 258101). F1 отдельной схемы отката не требует: правка живёт в payload-слое,
   сохранённый текст PG не мутируется — откат кода на `e3c61445` возвращает прежнее
   поведение; кастом-данные владельца в PG не затронуты в принципе.
6. **Постдеплой-обязательства** — ЗАФИКСИРОВАНЫ (READY_FOR_LIVE в карте, CFG-07A.1,
   live_required=true): (a) healthz отвечает **2.58.102**; (b) payload-речек на реальных
   PG-байтах 7 кастомов: маркеры SF-семейства отсутствуют в effective, правки владельца целы
   → CFG-07A.1 `VERIFIED @ deployed`; (c) ERR=0 в логах после старта; (d) владелец —
   опциональная проверка §7 (не гейт). До (b) родитель CFG-07A.1 не DONE.
7. **Гейт** — ПАСС (честный). `requirements_gate.py check --stage review --slice CFG-07A
   --candidate 211a8c1bdb992b30f90046b8bc1146a564f0b5dd --map plans/features/cfg/requirements-map.json`
   → **EXIT 1, ровно 5**: CFG-07A.3, CFG-07A.5 (поведенческие сценарии), CFG-07D.1, CFG-07D.2
   (поведенческие, вне поезда), CFG-07A.F (контейнер reuse-аудита SOUL-01/04/02/16).
   Маскировки нет: CFG-07A.1 честно `READY_FOR_LIVE`; .2/.4/.6/.7/.8 VERIFIED с evidence.

## Связка вердикта

Кандидат `a3535b68` (полный SHA выше); любой последующий код-коммит/конфиг-дельта
инвалидирует прогоны п.4 и байт-равенство п.2 — нужен recheck. F1-ревью REV-CFG07A-F1
(Approved 9/9) остаётся действительным: байт-равенство подтверждено на кандидате.

## Инструкции (для Orchestrator/DevOps)

```
git push origin a3535b68a3220f5a239ed7df3eb1a24f1e1d0873:refs/heads/master
git push origin e3c61445:refs/heads/release/fix-2.58.101   # рубеж отката
```
Далее штатный деплой-пайплайн → постдеплой-речек п.6 (healthz/PG-байты/ERR) →
CFG-07A.1 VERIFIED @ deployed + `--stage release`.
