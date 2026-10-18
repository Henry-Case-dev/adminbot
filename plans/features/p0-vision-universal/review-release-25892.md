# REV-REL-25892 — вердикт (релиз 2.58.92: P0V FIX2 + ADD-TR FIX2)

Независимый аудит релиз-пакета. Режим read-only: деплой и push НЕ выполнялись;
этот коммит — только данный документ. Прод до релиза — 2.58.91 @ `f2a6248a`.

Кандидат: bump `2c28e2a1` (parent `f7a14994` = V-FIX2; TR-FIX2 = `9d310996`).
Вход: отчёт `release-25892-report.md` (коммит `e90e9c7b`), evidence
`evidence/release-25892/**`, скрипт `deploy_25892.py` (`10322d72a735`),
`rel92_final.sh` (`bd4d91c2c7c2`), ветка `release/fix-2.58.91` @ `f2a6248a`.
Верификация — в изолированном worktree `wt` @ `2c28e2a1` + главное дерево
(только чтение) + мои прогоны ниже.

## 1. Bump — подтверждён

31 файл, +33/−33 (settings + README + F8-meta + 24 py-пина + 4 JS-пина);
содержимое коммита — ТОЛЬКО версионные строки `2.58.91 → 2.58.92` (фильтр по
не-версионным строкам пуст). `APP_VERSION = "2.58.92"` (settings), meta:
APP_VERSION 2.58.92 + HEAD (short) `f7a14994`. Упоминаний `2.58.91` вне
plans — ровно 20, все исторические аннотации «live 2.58.91» в
комментах/докстрингах/тестах (ни одного пина).

## 2. Дельта `f2a6248a..2c28e2a1` — изоляция подтверждена

88 файлов = 49 plans + 39 non-plans (7 runtime + README + 31 tests);
runtime-вайтлист деплой-скрипта (7) == runtime-дельта (set-equality, мой
прогон + `check_deploy_25892.py`). Содержимое сверено (≥4 файлов):
`mca_vision.py` `f8cb004c6c84` и `routes.py` `d54cc29695c7` — мои же биндинги
из ревью V-FIX2/RECHECK; TR-FIX2-хунки прочитаны: `direct_chat_service`
(медиа-цель reply-приоритетом), `direct_execution` (target из
`media_target_message_id`; референтный claim из replied, bounded 300),
`tool_router` (ToolContext `reply_source_*`/`media_target_message_id`;
recognize_image priority; envelope-цель = replied), `temporal_factcheck`
(`is_referential_claim`, bounded 80, «свой что-claim» не подменяется);
`settings.py` — только версия. Sanity-трио (telegram_send / fullscreen-policy /
prompt_composer) — diff к проду ПУСТ (байт-в-байт). Строки: 7 файлов +417/−36
(мой `--shortstat` совпал).

## 3. Числа — перепроверены (логи + мои прогоны)

- Полный pytest (worktree): **14447 passed / 9 failed** — лог сверен;
  база 2.58.91 = **14432/9** ⇒ **+15** = ровно новые тесты (TR-FIX2 8 +
  V-FIX2 7) — арифметика сошлась.
- 9-е падение (`history_cli::test_scope_is_required`) — env-артефакт чистого
  checkout, воспроизведён мной в трёх точках: [A] главное дерево (untracked
  `migrate_history/`, 4 элемента) — **1 passed**; [B] `wt` @2c28e2a1 —
  **1 failed** (то же сообщение); [C] чистая прод-база `f2a6248a` —
  **1 failed** идентично. Механизм: `manage.py` при отсутствии охвата сначала
  требует каталог `migrate_history/`. Дельта ни при чём.
- 8 остальных падений — те же пре-существующие (asap7×2, mca01×1, t5150×5),
  что в базах 25890/25891; clock-window тест зелёный (03:44 Екб — вне окна).
- Мои прогоны (все exit 0): TR-FIX2 **8**; vision-core **54**; `-k "fix2 or
  per_chat_context"` **7**; UI e2e **7**; speech-e2e **failures=0, POST=21**
  (webroot = wt); js-sweep **88 файлов / 0 падений**; реестр
  `gen_param_registry --check` **579 == REGISTRY**.

## 4. Деплой-скрипт (офлайн) — NF-фиксы 25891 сохранены

`check_deploy_25892.py` **EXIT 0** (мой прогон): EXPECT12 12/12, вайтлист 7/7
== дельта, BUMP == HEAD (worktree). Все **12 хэшей EXPECT12** я независимо
сверил из git-объекта `2c28e2a1` — 12/12 OK (вкл. sanity-трио = прод-значения).
NF-фиксы подтверждены в коде: `checked_out`-гейт (tree-restore только после
реального checkout, `CO_RC=0`), set-equality вайтлиста (`sorted`), tree-restore
→ `release/fix-2.58.91` / detach `PROD_REF` (не 2.58.88 — без downgrade),
WARNINGS-summary, SERVED_EQ (app.js/app.css), scrub секретов
(`SECRETS.extend` + `scrub`). Гейты: B3 `merge-base --is-ancestor BUMP
origin/master` (fail-closed до push); D1 несовпадение хэшей → abort →
`_tree_restore`; F2 RESTART_RC=0 + пустой T0 → `_rb` (cfg1-2.58.88);
F3 healthz-loop до 2.58.92, иначе `_rb`; G served-bytes + PAGE_VER=15/
SUBST_CSS=2; J `rel92_final.sh` (SKIPS=0-контроль, FIX2- и регрессионные
маркеры, SERVED_EQ, PAYLOAD SHA12, журнал/миграции/user_version).
`PROD_REF=f2a6248a`, `BUMP=2c28e2a1`, `EXPECT12=12` — совпало.

## 5. Док/чеклист — соответствуют

Состав = ровно два фикса (TR-FIX2 reply-путь; V-FIX2 воркер/429/state) с
человеческим описанием; откат: `release/fix-2.58.91` (abort до рестарта, без
рестарта) + `fix-2.58.90` + штатный `cfg1-2.58.88` (после рестарта); чеклист
(a–h) покрывает healthz/SKIPS=0/per-chat state ВКЛЮЧАЯ пробу/reply-на-фото/
«это правда?»/пробу-429/уборку/экономику; риски честные (429 — лимит
провайдера; пре-сущ. падения; mca09-флейк; d11-pollution; LOCKED-оговорка;
WebView — postdeploy RFL агентом, PET).

## Наблюдения (не блокирующие)

* B3 принимает любой tip origin/master, СОДЕРЖАЩИЙ bump; чужие runtime-файлы
  в tip ловит C-стадия (вайтлист, fail-closed). Чужие non-runtime (tests/docs)
  прошли бы молча, но на прод-рантайм не влияют — приемлемо.
* D2-маркеры логируются, но abort решается хэшами (сильная привязка);
  маркеры перепроверяются postdeploy в `rel92_final.sh` — ок.
* `PAGE_VER=15/SUBST_CSS=2` — grep-счётчики версии в отданном web/ (файлы
  дельтой не тронуты, семантика с 25891 сохранена).
* `history_cli`-артефакт — только чистые checkout'ы (CI/полный прогон);
  прод не затронут (тест на проде не выполняется). Опциональная гигиена теста
  — не в этом релизе.

## Леджер/статус

Пакет **готов к контролируемому деплою**. Живые пункты §4 (SKIPS=0 в окне
≥10 мин; per-chat state включая пробу; reply-на-фото; «это правда?»; проба/429;
уборка; экономика; WebView) — **READY_FOR_LIVE**: выполняет DevOps/приёмка
ПОСЛЕ выката, затем фиксирует VERIFIED; при провале — `_rb`/честная запись.
Предусловие: push `master` (B3 fail-closed); желательно push
`release/fix-2.58.91` (иначе tree-restore идёт detach'ем на `f2a6248a` —
объект на проде есть).

## Вердикт

**Approved** — релиз-пакет 2.58.92 (bump `2c28e2a1`, V-FIX2 `f7a14994`,
TR-FIX2 `9d310996`) проверен: дельта изолирована (7/7), хэши 12/12, числа
14447/9 с полной атрибуцией (8 пре-сущ. + env-артефакт, +15 новых),
скрипт с NF-фиксами и fail-closed гейтами, чеклист/откат полны. Деплой — за
DevOps/Orchestrator; родительский статус DONE — только после §4-приёмки.
