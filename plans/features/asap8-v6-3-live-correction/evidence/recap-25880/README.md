# RECAP-25880 — evidence index (frontend @ DEPLOYED 31c16555, 2.58.80)

Связка: detached worktree `%OPENCODE_WORKFLOW_SCRATCH%\recap-31c16555` (удалён после прогона),
`HEAD = 31c165556dbe8c289606bd6bee1af49bb72d5794` = deployed.

## Fingerprint (полные sha256 в `fingerprint.json`)

| Файл | sha256 (сокращённо) | vs deployed |
| --- | --- | --- |
| `web/app.js` | `9774da6a…9cb8ac` | = ✓ |
| `web/index.html` | `e209d5fa…6b3e0` | = ✓ |
| `web/static/app.css` | `70975eb2…3c887be2` (и отданный локально по HTTP) | = ✓ |
| `services/param_catalog.py` | `1981d338…d15ba7` | = ✓ |
| `config/settings.py` | `5a31a277…1b9f722fd` | = ✓ |

## Файлы

- `_31c16555_<surface>_<WxH>.png` — матрица: status / analytics_overview / analytics_processes /
  modules / editor_prompts / cover_editor × 8 вьюпортов (320×700, 360×780, 390×844, 430×932,
  768×1024, 1024×768, 1440×900, 667×375). 48 PNG, whole-viewport (IHDR == вьюпорт).
- `_31c16555_{editor_prompts_l1_focus,direct_models,shell_more_open,fullscreen_on,tdesktop_policy,
  rowa_390_zero,rowa_667_right44,rowa_320_lr24}_<WxH>.png` — 11 дополнительных состояний.
- `capture_states.json` — 59 состояний: пробы (header rect/height, hOverflow, shell-класс,
  prompt-keys, L1-present, textarea key/len), inset-кейсы, served CSS sha256/формулы, stub_notes.
- `png_index.json` — per-file width/height/bytes/sha256 (машинный whole-viewport proof).
- `png_variance.json` — anti-blank (71 PNG, std ≥ 18.9, min/max широкий).
- `fingerprint.json`, `verify_summary.json` — привязка и машинные проверки (все hard-чеки pass).
- `_31c16555_suite_*.log` + `_31c16555_suites.txt` — результат-строки шести сьютов (полные stdout).
- `_31c16555_capture_stdout.log`, `_31c16555_route_probe.json`, `_31c16555_overflow_diag.txt`.
- `suite_w2_fullscreen/` — fingerprint-clean артефакты W2-fullscreen (S1…S8, DSF=2) + `_results.json`.
- `harness/` — скрипты капчура/проверок (cap.py, probe_routes.py, diag_overflow.py, verify_evidence.py,
  fingerprint.py, index_pngs.py, png_variance.py).

## Как воспроизвести

1. `git worktree add --detach <dir> 31c165556dbe8c289606bd6bee1af49bb72d5794`
2. шесть сьютов из `<dir>/tools/` (python из `C:\Code\Python\adminbot\.venv`)
3. `harness/cap.py` → PNG + `capture_states.json`; далее `harness/index_pngs.py`, `harness/png_variance.py`,
   `harness/fingerprint.py`, `harness/verify_evidence.py`.
