# Prompt release log / factory activation — 2.58.203

Источник: журнал `admin_bot` в процессе, стартовавшем 2026-11-14T18:56:49Z
(после рестарта деплоя). Полные строки — `journal-summary.txt`.

## 1. Строки `[prompt_release]` (3 шт.)

```
18:56:52.075 [prompt_release] manual scope: заводская ревизия rev:9ed7b22b0d8c
  записана в историю, сохранённая редакция rev:d31300ef35a0 остаётся активной
  | block=checkup.base.system | scope=chat | chat=-1002661910336

18:56:52.127 [prompt_release] activation | release=evol-016-cutover
  | block=checkup.base.system | scope=global | action=activate
  | outcome=applied | detail=factory_activate
  | rev=rev:a2a369bba312 | factory_rev=fac:93c42f967ef8

18:56:52.128 [prompt_release] релиз применён | release=evol-016-cutover
  | blocks=112 | changed=1 | retired=0
```

Строк `persisted speech value withheld` — **0**.

## 2. Что это значит

- Метка чек-апа сменилась (`checkup-p0-24-10-mixed-state`), поэтому план
  релиза для этого блока стал `activate` (было `noop` на 2.58.202), при
  неизменных байтах заводского текста: 3 462 симв.,
  sha256 `3140bb36404467973eb4d34afccb5409add55262d251d6d7a60b8df333980052`.
- **Global-слой**: активирована новая заводская ревизия `rev:a2a369bba312`
  (`fac:93c42f967ef8`), активация **2944** `deploy_activate/applied/
  factory_activate`. В `bot_settings.prompts.checkup_system_prompt` теперь
  тело 3 462/`3140bb36…` без Betterstack и без 401
  (было 3 030/`b0c70f97…` с Betterstack/401).
- **Чат владельца** (manual-редакция `rev:d31300ef35a0`): сработал guard
  EVOL-016 — заводская ревизия записана в историю (`rev:9ed7b22b0d8c`),
  сохранённая редакция остаётся активной, активация **2945**
  `deploy_activate/skipped_same/factory_superseded_manual`. Ни значение,
  ни chat-override не перезаписаны.
- `retired=0`, `changed=1` — релиз не снял ни одного блока и не менял
  ничего, кроме этой строки.

## 3. Состояние журнала ревизий после релиза

```
activations (block=checkup.base.system)
  2945  chat    rev:d31300ef35a0  deploy_activate  skipped_same  factory_superseded_manual  fac:93c42f967ef8
  2944  global  rev:a2a369bba312  deploy_activate  applied       factory_activate           fac:93c42f967ef8
  2943  chat    rev:d31300ef35a0  manual_rollback  skipped_same  activate:manual            15:14:52Z (до релиза)
  2942  chat    rev:d31300ef35a0  manual_rollback  applied       activate:manual            15:14:52Z (до релиза)
  2941  chat    rev:9ed7b22b0d8c  deploy_activate  applied       factory_activate           13:42:28Z (EVOL-016 cutover)
  2940  chat    rev:d31300ef35a0  manual_edit      applied       owner_edit                 06:11:54Z

revisions
  rev:a2a369bba312  factory  global  3 462  3140bb364044  fac:93c42f967ef8  active (global)
  rev:9ed7b22b0d8c  factory  chat    3 462  3140bb364044  fac:d263c52f7871  history, retired=false
  rev:d31300ef35a0  manual   chat   12 469  31d175065461  —                ACTIVE (chat), retired=false
  rev:3be4841bca08  factory  global  3 030  b0c70f974e0e  fac:d263c52f7871  history
```

## 4. Владельческая редакция — байтовая проверка

```
revision_id  rev:d31300ef35a0
origin       manual
scope        chat
retired      false
body_chars   12 469
body_sha256  31d1750654615bf4e69e861ae66f393b31546b34982c7d5613052b67133b3701
created_at   2026-11-14T06:11:54.954581Z
pre == post  да (снапшот до деплоя и после идентичны)
chat override present, 12 469 chars, sha256 31d17506…  — сохранён
```

Верификация «до/после» — `raw/snapshot_pre_203.json` /
`raw/snapshot_post_203.json`, проверка `verify203.json`
(`manual_revision_unchanged`, `manual_chat_override_present_12469_31d17506`).
