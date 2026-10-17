# Release evidence — SOUL-1 2.58.86 (`release/soul1-2.58.86`)

Индекс артефактов релиза. Всё снято на точном дереве ветки
(`eafbe2e7b792c74eeb91735e183b767c6b85d73c` = деплой-тип; артефакты-доккоммиты
идут после) или на сервере в рамках релизного прогона 2026-10-17 21:44–2x:xx UTC.

## Изоляция и состав

| Файл | Содержание |
|---|---|
| `isolation-classification.txt` | классификация всей дельты vs база (`95526863`): 0 неклассифицированных |
| `delta-vs-base.txt` | 628 файлов дельты (полный список) |
| `delta-files-with-stats.txt` | numstat по дельте |
| `wg-byte-equal.txt` | WG-артефакты (рефракция/пробы/fullscreen-policy/e2e-инструмент) байт-в-байт проду |
| `web-delta-analysis.txt` | 3 web-файла = прод-байты + SOUL/W7-строки; WG-маркеры не удалены |
| `equivalence.txt` | `services == 72b91d6e` (F1+F3), `web == 0ca661fe`, CFG отсутствует, stray-путей нет |
| `hashes.txt` | sha256_12 ключевых файлов: head / prod / master |
| `secret-scan.txt` | секрет-скан дельты: только тестовые дубли |
| `preflight-frozen-check.txt` | frozen-инварианты (полигон/линзы/ассеты/LF) против базы: OK |

## Preflight-прогоны (точное дерево ветки)

`preflight-node-guards.txt` (87/0), `preflight-soul1-set.txt` (599),
`preflight-parity.txt` (13), `preflight-registry-check.txt` (575),
`preflight-perimeter.txt` (3917/0), `preflight-embedding-sweep.txt` (534),
`preflight-adjacent-tests.txt` (70), `preflight-ui-fs-matrix.txt` (12/12),
`preflight-ui-w7-explain.txt` (5/5), `preflight-ui-shell-e2e*.txt` (RED, A/B на
базе — см. `w2-shell-e2e-diagnosis.txt`), `preflight-ui-w6-speech-*.txt` +
`w6-e2e-diagnosis.txt` + `fixture-regenerated-by-dump-script.json` (RED на
устаревшей фикстуре / 0 failures на пере-снятой; файл в репо не менялся).

## Капчуры до включения и деплой

`capture-before.txt` — read-only снимок прода до включения (PG-backup,
(ii) `summary_editor`/per-chat `summary_cover_style` + маркер-скан, F5
`personas`/`persona_traits`, F2/F4, состояние осей OFF), `enable.txt`,
`verify-after.txt`, `deploy-run.txt` — единый деплой-прогон (fetch/checkout/
hash/markers/2×graceful-restart/верификация/пост-пробы/журнал), `recon.txt`.

## Инцидентные находки (не релиз)

`w2-shell-e2e-diagnosis.txt` + `incidental-u02-dropdown-{branch-390,prod95526863}.png` —
регрессия слоя стекла (WIN-GLASS-P0 2.58.85): мобильный dropdown «Раздел: …▾»
в «Аналитике» перекрыт карточкой (тап не доходит); воспроизводится на
задеплоенной базе идентично; к SOUL-1 не относится.
