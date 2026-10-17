# REVIEW-LEDGER-PASS — независимая проверка ре-анкора карт на прод `0b7a0aca` (2.58.84)

| Поле | Значение |
|---|---|
| Коммит | `d98e55c6ab983965bb0494a45cc9f4a10aa647fd` (4 файла, +6084/−4897), родитель `a891b721` |
| Кандидаты | ревью-кандидат soul-1 `6094a2cf…`; прод-релиз `0b7a0aca416a418e099e157eca77d0a3137b3405` (2.58.84) |
| Проверено | состав/JSON/конвенции; диff a891b721→d98e55c6; привязка v6.3 (FE-FULLSCREEN+V06) и soul-1 (W7); гейты verbatim; прод-доказательство SOUL-13.2 |
| Вердикт | **Approved** — состав и привязка воспроизводятся; статусы честные; блокеров нет. Одна поправка к описанию: земля AU-8 в коммите **не «без семантики»** (см. §2) |

## 1. Состав и конвенции

- 4 файла: v6.3-карта `5984/4889`; `plan.md` `18/4`; amendment `1/1`; soul-1 main `81/3`. Чужих файлов нет.
- JSON валидны; v6.3-карта — **indent=1 + полностью CRLF** (AU-8-стиль, было indent=2); soul-1 main/amendment — свой indent=2 + CRLF, не менялись; `plan.md` — LF. Lone-LF нет ни в одной; число CRLF = числу строк.
- soul-1 main: top `deployed_commit := 0b7a0aca`; изменены **ровно 13 W7-строк** (+1 evidence каждая) + top-поле; статус изменён только у SOUL-13.2 (RFL→VERIFIED); строк не добавлено/удалено. Amendment: `1/1` — только `deployed_commit`.

## 2. Дифф `a891b721 → d98e55c6` (v6.3-карта) — фактическая картина

- top: `candidate_commit`=`deployed_commit`=`0b7a0aca…`; строк 222/222, добавлено/удалено 0.
- **Свой дифф лейна:** 28 строк с evidence, ссылающимся на `release-fs-25884` (27 required FE-FULLSCREEN + V06); **9 reason-переписей FE-FULLSCREEN** (L00014, L00016, L00178, L00200, L00203, L00204, L00227, L00230, L00231) + reason V06 (L00431); FOLLOW-UP-наблюдения в 4 строках (U07-SYM-ANDROID, REQ-U07, REQ-U07-2, U07.2a) — **без дублей строк**.
- **Земля AU-8 (ранее незакоммиченная) семантична, а не только формат**: 27 смен статуса (18 BLOCKED→17 RFL + U07.1a→PENDING; 4 FE-GLASS VERIFIED→RFL; 3 FE-GLASS VERIFIED→PENDING; 2 PENDING→VERIFIED), evidence-реанкор с кандидатом `31c16555` (~105 строк), переанкор excerpt/sha (40 только-excerpt + 20 только-sha + смеси), `U07.1a` disposition→`user_excluded` + `user_approval_ref` (директива владельца), `U07.1e` acceptance приведён к директиве (мягкий exit отменён), reason-тексты «Аудит 18.10…». Итоговые счётчики совпадают с опубликованными AU-8: **VERIFIED 135 / RFL 59 / PENDING 28 / BLOCKED 0**.
- Смешения нет: release-ссылки встречаются **только** в FE-FULLSCREEN+V06; спот-чек 10 строк вне FE-FULLSCREEN показал исключительно классы AU-8 (статус/reason/evidence@31c16555/excerpt-sha) — посторонних семантических правок не найдено.

## 3. v6.3: привязка 27 required-строк и честность статусов

- FE-FULLSCREEN: 28 строк, required **27** (U07.1a — `user_excluded`), все 27 с evidence@0b7a0aca; +V06 = 28-я. Ссылки `release-fs-25884-report.md` + `evidence/release-fs-25884/**` на диске существуют (были untracked — фиксируются этим docs-коммитом).
- **8 RFL owner-live** в FE-FULLSCREEN (U07-SYM-DESKTOP, U07-LAUNCHMODE, REQ-U07, U07.1e, REQ-U07-3, U07.3b, U07.3c, REQ-U07-HARD) — причины говорят только о живом наблюдении (owner-live; OQ-1 отменён владельцем/PET_PROJECT); ни одна RFL не закрыта.

## 4. soul-1: запись к 0b7a0aca и SOUL-13.2

- Все 13 W7-строк получили evidence@0b7a0aca с явной пометкой: fs-слой задеплоен (policy `96db0642…` в проде байт-в-байт), **не-fs элементы W7 (SOUL-13.4 embedding-диагностика, W7-ханки) в релиз НЕ входили** — предупреждение вынесено прямо в observation (SOUL-13.4 остаётся на dev-линии).
- **SOUL-13.2 → VERIFIED** подтверждаю по сырому `evidence/release-fs-25884/ev_deploy_run.txt` (Фаза E, 18:46 UTC): `/web/static/glass-teststand.html` = **404**, `/static/glass-teststand.css` = **404**, живые пути `/web/`, `/web/static/app.css`, `/web/app.js`, `/static/app.css`, `/web/static/fullscreen-policy.js`, `/healthz` = **200**, healthz `{"status":"ok","version":"2.58.84"}`, live POLICY_SHA = `96db0642…`. Overclaim нет.
- Дополнительно сверено: `hashes.txt` (9 fs-файлов = наши отпечатки), `isolation-classification.txt` (40 = 9 fs + 31 пин, непокрытых 0), `soul1-diff-empty.txt` = 0 байт, e2e на релиз-дереве **12/12 (166)**, postdeploy-проба прода (кнопка не вводит в заблуждение без `me`, §8 off, 0 console errors).

## 5. Гейты (мой прогон, verbatim)

- v6.3 `review --slice FE-FULLSCREEN --candidate 0b7a0aca`: `stage=review inventory=148 manual=74 scoped=27 errors=0` EXIT 0;
- v6.3 `plan`: `148/74/0/0` EXIT 0; soul-1 main `plan`: `101/97/0/0` EXIT 0; amendment `plan`: `66/28/0/0` EXIT 0;
- soul-1 `review --slice W7 --candidate 6094a2cf`: `101/97 scoped=13 errors=0` EXIT 0.
Все совпадают с `plan.md §W7 RELEASE re-anchor`.

## 6. Поправка для отчётности (не блокер)

Формулировка «AU-8-реформат карт (whole-file но без семантики)» неточна: в коммите лежит **семантическая** переклассификация AU-8 (18→0, V135/RFL59/P28, стеклянные демоции, evidence@31c16555, excerpt/sha-реанкор) — она задокументирована в `workflow_state.md` и совпадает с опубликованными числами AU-8, но в сообщении коммита и в `plan.md` AU-8 явно не названа. Рекомендация: при следующем касании — указать это в истории (постфактум-правку не требую).
