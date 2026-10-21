# REL-258106 — деплой 2.58.106 и live-пробы (DevOps, 21.10.2026)

Кандидат: `83012fcf` (runtime-дельта, REV-REL-258106 **Approved**); поверх — docs-коммиты
`1aadf16b`, `db2fa706`, `dad9afce` (docs/evidence/карта, runtime не трогают).
Задеплоен HEAD `dad9afce` (origin/master). ΔDDL=0. Планшет — `deploy.json`.

## Выкат

| Параметр | Значение |
|---|---|
| T0 | 2026-10-21T10:35:28Z (рестарт плановый) |
| healthz loopback:8000 | 200 `{"status":"ok","version":"2.58.106"}` |
| healthz публичный 443 | 200 `2.58.106` |
| Сервис | active/running, MainPID=192071, **NRestarts=0**, ExecMainStatus=0 |
| Journal с T0 | 739 строк (на 10:53Z), **0 CRIT / 0 Traceback** |
| Блобы сервера vs кандидат | web/app.js `c35adefe8310`, web/static/app.css `08913f637f00`, web/index.html `c06b0d47a5dc` (+ speech.py, style_policy.py, chat_migration.py, settings.py в main-прогоне) — **все OK** |

## Live-пробы

**SOUL-14.1 — VERIFIED.** `GET /api/speech/overview` (валидный initData, подписанный
серверным токеном; audit-user, read-only GET): блок `layers` присутствует, оси
`l1` + `self_model`; l1 `{available,enabled,fallback}` = True;
self_model `{available:True, enabled:True, applied:0, rejected:8, stale:False,
fallback:False}` — реальные числа. Публичный HTML (443) содержит
`[data-speech-layers]`; в отданном `app.js` (blob-равен кандидату)
`speechLayerNodes` = 7 узлов (Core, SelfModel, L1, lessons, examples, humor,
Writer), «—» при отсутствии данных, ничего не выдумывается.

**SOUL-14.2 — READY_FOR_LIVE (честно).** Выкат подтверждён
(style_policy.py blob-равен кандидату), но `mca_events` не содержит
`event_name='speech_extent'` ни за окно наблюдения (T0..10:54Z), ни вовсе:
реальных сообщений не было, генерить сообщения агенту запрещено. События
появятся с первым реальным проходом style policy; style OFF → событий нет —
норма, не регресс. Строка остаётся READY_FOR_LIVE до живого подтверждения.

**SOUL-14.0 (umbrella)** — остаётся VERIFIED (бинд `dad9afce`, критерий
«артефакты всех детей»; регресса на 2.58.106 нет); `reason` дополнен
постдеплой-фактами, 14.2 трекается на своей строке.

## SSH/fail2ban-дисциплина

recon 10:32:22Z (~15с) → пауза >90с → основной прогон 10:35:28Z (pull --ff-only →
HEAD=dad9afce → рестарт → healthz/journal/mca) → 4 одиночных верификационных
коннекта 10:38–10:53Z с паузами ≥70с (завершение обязательных live-проб;
без поллеров, auth-отказов 0, креды не печатались). Сообщений в чаты: 0.

## Откат

Ветка `release/fix-2.58.105` = `a6246e33` запушена в origin.
Процедура: `git checkout release/fix-2.58.105` + `sudo systemctl restart admin_bot`.
Миграций нет (ΔDDL=0), откат чистый.

## Замечания (не блокеры)

- Серверный urllib не соединяется с loopback:8000 (вероятен env-прокси), curl с
  `--noproxy '*'` работает — артефакт проб, не релиза.
- Header-передача initData давала 400 «Invalid HTTP request received»;
  query-фолбек `?initData=` (deps.py) работает штатно.
- `review-migfix.md` на диске отсутствует — в хвост не включён; носитель
  B12.6-вердикта: `plans/features/asap8-v6-3-live-correction/evidence/review-exec-tails.md`.
