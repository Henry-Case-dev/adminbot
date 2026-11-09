# REL-258154 — выкат 2.58.154 (RC v5 «целостность контекста ответа») на production

Дата: 04.11.2026, 00:53–00:57 UTC. Сервер: `192.255.209.205`, каталог `/var/www/admin_bot`, unit `admin_bot`.
Результат: **VERIFIED** (обязательные проверки пройдены, откат не нужен).

## DEPLOY_SOURCE

- Артефакт: **`2de11dc0c3a836b44e047484a80ddb0425891ad0`**, ветка `release/2.58.154` (запушен в origin).
- Предыдущий прод: `e52a06b2b8cdcb6c01c83bda46d7a406596f2088` (2.58.153) — точка откатa.
- Дельта к `c3cbdafb` (артефакт, проверенный ревьюером) — только `tests/test_asap_w1_semantics.py`
  (переутверждение пинов канона). Рантайм-код на сервере побайтно равен проверенному кандидату.
- `MUTABLE_WORKTREE_REQUIRED: no` — выкат идёт из immutable-коммита, локальное дерево проекта не использовалось.
- Write scope прода: checkout `/var/www/admin_bot` (ветка `release/2.58.154`) + рестарт unit.

## Проверки до выката

- Прод на `e52a06b2`, branch `release/2.58.153`; tracked-dirty 0; untracked — только `.cache/` (runtime).
- `healthz` 200 `2.58.153` (loopback, SNI, публично), NRestarts 0, 1 процесс, `user_version` 41,
  медиа 66 файлов, свободно 61 ГБ.
- Целевой коммит в локальном объектном сторе сервера отсутствовал → сделан `git fetch --prune origin`.
- План выката приведён к неразрушающей форме с целевым SHA `2de11dc0`
  (`plans/features/evol/reports/rc-v5-final-acceptance.md` §5): `git status --porcelain` → СТОП при грязи →
  `git fetch --prune origin` → `git cat-file -e <sha>^{commit}` → `git checkout -B release/2.58.154 <sha>` →
  `git rev-parse HEAD` → один рестарт. `reset --hard`, `clean -fd`, `checkout -f`, stash не применялись.

## Выкат

- `RESTART_UTC=2026-11-04 00:55:49`; `ExecMainStartTimestamp=00:55:51`; MainPID 1794505; **NRestarts 0**; процессов 1.
- `git rev-parse HEAD` = `2de11dc0c3a836b44e047484a80ddb0425891ad0`, `APP_VERSION=2.58.154`, дерево после checkout чистое.
- Backup/DDL: DDL и миграций в дельте нет, `pg_db.py` не тронут, `user_version` 41 → 41. Перед выкатом снят
  снимок живых промптов (`/root/deploy-258154/pre_prompts.txt`) для байтового сравнения после.

## Health

| Проверка | Значение |
| --- | --- |
| `/healthz` loopback (`127.0.0.1:8000`) | 200 `{"status":"ok","version":"2.58.154"}` (00:55:52, 00:56:00, 00:57:11 UTC) |
| `/healthz` SNI-резолв на loopback | 200, `2.58.154` |
| `/healthz` публично (`https://admin-bot.duckdns.org`) | 200, `2.58.154` |
| `NRestarts` | 0 |
| Процессов в cgroup | 1 |
| `PRAGMA user_version` | 41 (без изменений) |
| Медиа | 66 файлов (как до выката) |

## Канон: доказательство активации (три независимых источника)

1. `venv/bin/python -m services.prompt_factory report`:
   `direct.base.l2_writer` → `fac:44736968bc76(l2-writer-self-correction-rca1)`,
   `blocks=112 fingerprint=e9dc109330a8`; `FACTORY_REVISION_SEALS`=111, `seal_integrity()={}`.
2. PG `prompt_activations`: `id=2916 kind=deploy_activate outcome=applied fac=fac:af56db513733
   rev=rev:c118e25b3fc3 scope=global ts=2026-11-04 00:55:54`; ревизия `content_sha12=44736968bc76`, 7 328 симв.
   Активное значение `prompts.direct_chat_verbalizer_system_prompt` в `bot_settings` = `44736968bc76` (7 328 симв.,
   было `68f0233d7050` / 5 078).
3. `GET /api/prompts/catalog` (admin initData, HMAC): HTTP 200, `count=112`,
   `direct.base.l2_writer` → `fac:44736968bc76(l2-writer-self-correction-rca1)`, `scope=global`.

Расхождений между источниками нет.

## Живые промпты владельца: байтовое сравнение до/после

| Ключ | До выката | После выката | Ожидание | Итог |
| --- | --- | --- | --- | --- |
| `prompts.meme_joke` (global) | `2f30ca1f9a6b` | `2f30ca1f9a6b` | `2f30ca1f9a6b` | совпадает, не изменён |
| `prompts.meme_image` (global) | `f81fe7e4b505` | `f81fe7e4b505` | `f81fe7e4b505` | совпадает, не изменён |
| chat-override `-1002661910336` joke | `71303ff62029` (1 363 симв.) | тот же | — | не изменён |
| chat-override `-1002661910336` image | `11cf82f45c3a` (566 симв.) | тот же | — | не изменён |
| chat-override `-1004482340693` joke | `4bc3425f2f3d` (261 симв.) | тот же | — | не изменён |
| chat-override `-1004482340693` image | `11388ab3a936` (372 симв.) | тот же | — | не изменён |

Пер-чат override-ы мемных промптов — собственные тексты владельца (они и раньше отличались от заводских),
выкат их не тронул: sha12 до и после совпадают побайтно. Заводские/глобальные значения равны ожидаемым.

## Журнал (с 00:55:49 UTC)

- `Traceback` 0, `CRITICAL` 0, `Exception`/`database is locked` 0, `publication_stale` 0
  (и 0 в прежней формулировке), `missing prompt` 0, `[ini-pub]` ошибок 0.
- `ERROR` 4 — все одного класса: `services.prompt_release_policy → activation_drift` на старте,
  блоки `initiative.meme.image` / `initiative.meme.joke`, scope=chat, оба чата.
  Смысл строки: журнальная метка `journal_sha` = заводская (`2f30ca1f9a6b` / `f81fe7e4b505`), активное
  значение = пер-чат текст владельца; «источник истины на этот старт: PG-значение, активации нет».
  Данные не перезаписываются (подтверждено байтовым сравнением), `prompt_release_policy.py` в дельте релиза
  не менялся. Прошлый старт (03.11 10:34:36) дал 1 такую строку, сейчас 4 — разница в том, какие именно
  пер-чат тексты владельца расходятся с журналом, а не в новом коде. Не блокер; backlog: снизить уровень
  логирования или писать no-op-активацию, чтобы мониторинг ошибок не шумел на каждом рестарте.

## Поведение

Наблюдение только по реальному трафику, синтетических сообщений в живые чаты не отправлялось.
После рестарта (~1.5 мин наблюдения) в журнале только плановые задачи (`VisionMediaWorker._tick`,
`WATCHDOG_SWEEP`, `UptimeHeartbeatService._heartbeat`) — новых сообщений владельца за это окно не было,
поэтому живая проверка сценариев RC v5 на этом релизе ещё **не наблюдалась** (21 сценарий остаётся
UNVERIFIED до появления реального трафика). В PG 9 вызовов LLM за 30 мин до рестарта — прод-активность есть.

## Откат (не потребовался)

- Код: `git checkout -B release/2.58.153 e52a06b2b8cdcb6c01c83bda46d7a406596f2088` + `systemctl restart admin_bot`.
  Только код: DDL/миграций нет, `user_version` не двигался; канон возвращается первой ступенью лестницы
  (`68f0233d7050`).
- Мягкий рубильник: `flags.context_speech_projection=false` (или env `CONTEXT_SPEECH_PROJECTION_ENABLED=false`).

## Следы на сервере

`/root/deploy-258154/` — скрипт выката, postcheck, pre/post снимки промптов, журнал после рестарта,
логи fetch/checkout.
