# RELEASE-GLASS-ISO — сводка верификации (2.58.81 @ `6d4b9a7d`)

Все проверки — с прод-сервера (`/var/www/admin_bot`), read-only HTTP/SSH. Сырые транскрипты:
`ev_deploy_run.txt` (прогон деплоя), `ev_verify_run.txt` (финальная верификация).

## Хеши релизного коммита (`6d4b9a7d`, branch release/glass-2.58.81)

| Файл | sha256 |
|---|---|
| web/static/app.css | `c28d4c89fdb11401475b78fc72442cca419e6c113e924307f5cbbd7e31ef2cdf` |
| web/app.js | `828d265b187a531c9440b92ca11c7c6cdf04e58cd06e6c65affd6d2e270b28d7` |
| web/index.html | `0da0a7014594e5b87e3efa8f141eacbcc07d320d57b09db4840f3d0869ffd78f` |
| services/param_catalog.py | `1981d3382e2ee81222107027ead5e7e61ef438cbdc91afcd1c13e668d0d15ba7` (== 2.58.80: W1-каталог исключён) |
| config/settings.py | `fb4ea79205ffdd38cbb7808064e5c242512188c51cf1d287aff2dffc2b209686` |

Ожидаемые байты отдачи с подстановкой `__APP_VERSION__`→`2.58.81` (маршруты `/web/` и `/static/app.css`):
`eb93fd0d…8713` (index) и `b0b18b97…e41d` (css; CRLF→LF через text-mode read + подстановка).

## Файлы сервера == релизному коммиту

5/5 sha сошлись (app.css, app.js, index.html, param_catalog.py, settings.py).

## Отдача через 443 (caddy, --resolve loopback)

| Проверка | Результат |
|---|---|
| `healthz` | `{"status":"ok","version":"2.58.81"}` |
| `/web/` | 200; sha `eb93fd0d…` == ожидаемый substituted index; `2.58.81`×14, `2.58.80`×0; `scale="32"`×1; `lg-lens-map`×1; `glass-teststand`×0 |
| `/web/static/app.css` (raw mount) | 200; sha == raw commit file |
| `/static/app.css` (route с подстановкой) | 200; sha == expected substituted |
| `/web/app.js` (реальный путь бандла) | 200; sha == raw commit file |
| Тест-стенд: `/web/static/glass-teststand.{html,css,js}` + `/static/glass-teststand.{html,css,js}` + HEAD + `?v=` | все **404** (8 проб) |
| Живые ассеты | `/web/` 200, `/web/app.js` 200, `/web/static/app.css` 200, `/static/app.css` 200, `/static/glass-probe.js` 200, `/static/glass.js` 200 |

## Изоляция W1 на задеплоенном дереве

- `services/prompt_registry.py` — отсутствует; `services/prompt_factory.py` — отсутствует.
- `tests/glass-teststand/` присутствует; `web/static/glass-teststand.html` отсутствует.
- Runtime-проба (интерпретатор сервиса): `version=2.58.81`, ключ каталога `prompts.direct_l1_planner_system_prompt` присутствует, `lxml_html_clean=ok`, `trafilatura=ok`, `glass-probe.js` присутствует.

## Сервис и журнал

- `ActiveState=active SubState=running MainPID=2854731 NRestarts=0 ExecMainStatus=0`.
- Журнал после рестарта (с 2026-10-16 13:00:07): 292 строки, `ERROR=0 CRITICAL=0 Traceback=0 database is locked=0`.

## Локальные проверки ветки (см. отдельные файлы)

- `branch-log.txt` — 4 коммита поверх `31c16555` (3 cherry-pick + bump).
- `w1-diff-empty.txt` — 0 байт: diff по W1-файлам от `31c16555` пуст.
- `glass-identical-to-master.txt` — 0 байт: payload (web/, tests/js, tests/glass-teststand, requirements.txt, web_content_extractor.py, оба новых теста) побайтово == master `473f2cc1` (на пре-bump tip `2aa512e6`).
- `glass-identical-to-master-tip.txt` — на финальном tip в том же скоупе отличий только 4 JS-версионных пина (артефакт bump, ожидаемо).
- `isolation-vs-master.txt` — 65 файлов: tip ветки vs master = W1-файлы (35) + версионные файлы bump (31) − пересечение (1); других отличий нет.
- `node_glass_probe.txt`, `node_design_tokens.txt`, `node_hotfix7_10_after_bump.txt`, `pytest_guards.txt`, `pytest_tails_touched.txt`, `pytest_pins_after_bump.txt`, `e2e_shell.txt`, `e2e_fullscreen.txt`, `gen_registry_check.txt`, `bump_run.txt`, `gate-release-check.txt`.
