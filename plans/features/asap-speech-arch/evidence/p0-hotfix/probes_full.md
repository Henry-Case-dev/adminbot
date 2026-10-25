# P0 HOTFIX — full production-context probe (LANE FULL-PRODUCTION-PROBE, 2-й бюджет)

Статус: **BLOCKED (неполный прогон).** Реальный L1 Planner выполнен только для
old/A; L2 Writer (8 raw) и 9 проверок §5 не выполнены: единственный разрешённый
SSH-сеанс оборвался по транспорту во время матрицы. Ничего не выдаётся за
VERIFIED, deploy не выполнялся.

## 1. Что реально выполнено и чем подтверждено

Инструмент: `probes_full/harness_probe_full.py` (запускается на сервере, импортирует
код варианта; PG — read-only пул, SQLite — `mode=ro`; учёт usage и события
заглушены, чтобы не писать в БД). Smoke-прогон: `--root /var/www/admin_bot
--label old --case A --skip-l2`.

Реальные источники, прочитанные этим прогоном:

| Слой | Факт | Значение |
|---|---|---|
| PG | `SHOW transaction_read_only` | `on` |
| PG | ключей в `bot_settings` | 537 (значения не выгружались и не печатались) |
| PG | per-chat overrides | 6 ключей |
| PG | **источник Personality Core** | `bot_settings['character.core']` через `hot_config` → `prompt_composer.resolve_core_ref`; это НЕ отдельная таблица документов в `public` |
| SQLite | окно чата | 64 сообщения |
| SQLite | `graph_facts` | 40 строк |
| SQLite | `lore_stories` | 2 строки |
| SQLite | `mca_lessons` | 2 строки |
| SQLite | `chat_running_summary` | 1117 симв., sha12 `ec7a5231c9ba` |
| Prompt | база канала | 3081 симв., sha12 `83ff62bbee40`, source `global` |

## 2. Реальный system (old/A) по слоям композера

`system` = **13937** симв., sha12 `8c2c7edc3ee6`.

| Слой | Симв. | Статус |
|---|---|---|
| channel_contract | 3081 | rendered |
| **core** | **2507** | rendered (старый вариант) |
| identity (persona) | 5048 | rendered |
| context_lessons (lessons) | 141 | rendered |
| response_plan (extent) | 141 | rendered |
| expression | 1016 | rendered |
| style_policy_hint | 980 | rendered |
| self_model_traits | 0 | `self_model_folded_into_identity` |
| speech_understanding | 0 | `speech_absent` |
| humor_craft | 0 | `humor_no_strategy` |
| few_shot (expression examples) | 0 | `expression_examples_absent` |
| few_shot (samples) | 0 | `samples_absent` |
| channel_output | 0 | `channel_output_not_required` |

Отсюда честная граница: **13937 против 19–20k в проде**. Разница — слои, которым
нужен живой сервисный резолв с БД-объектом (`mca_sample_library`, expression
examples, speech, досье), а не только тексты. Это ограничение одинаково для old и
new, поэтому сравнение изменённых инструкций остаётся валидным, но «system
сопоставим по объёму с продом» утверждать нельзя.

## 3. Реальный L1 Planner (old, кейс A) — выполнен

- вход: system 8261 (`6c2ddc17c998`), контекст 2935 (`8a338ae33b60`),
  `l1_temperature` из конфига; 3.5 s; JSON распарсен.
- план: `action=reply`, `response_act=banter`, `extent=compact`,
  `structure=chat`, `tone=playful`, `confidence=0.95` (high), `source=llm`.

**Это важная находка.** Для A трасса показывала маршрут serious/research/normal, а
реальный L1 на том же вопросе и окне решает «banter / compact / chat». Значит:
1) восстановленный из трассы маршрут нельзя использовать как «план L1»;
2) для A новая analysis-директива по предикату `analysis_directive_needed` в
нормальном случае **не должна включаться** — сравнение 1×/0 нужно делать на том
плане, который реально отдаёт L1, иначе проверка измеряет не тот путь.

## 4. Что не выполнено

- L2 Writer: 0 из 8 raw (2 повтора × A/B × old/new). Процессы не стартовали.
- Полные `system`/`user` длины и sha12 для new/A, old/B, new/B; счётчики exact
  analysis 1×/0; `MODE_DEEP_RESEARCH_BLOCK`; Core 1246/2507 по вариантам.
- 9 пунктов §5 цитатами.
- Self-echo на `graph_facts.id=21255` / `lore_stories.id=4` исправленным кодом.

Причина: SSH-транспорт оборвался (`SSH session not active`) на этапе матрицы;
единственный разрешённый сеанс израсходован. Данные и staging на сервере живы:
`/tmp/p0-full-new` (new `9650e099`), `/var/www/admin_bot` (old `534ac7dd`),
`/tmp/p0-probe/probe_full.py`, `/tmp/p0_old_A_smoke.json`.

## 5. Точный следующий шаг (механический)

```
mkdir -p /tmp/p0-probe && cp -f /tmp/p0-full-new/probe_full.py /tmp/p0-probe/
cd /tmp/p0-probe && PY=/var/www/admin_bot/venv/bin/python
$PY probe_full.py --root /var/www/admin_bot  --label old --case A --out /tmp/raw_old_A.json
$PY probe_full.py --root /var/www/admin_bot  --label old --case B --out /tmp/raw_old_B.json
$PY probe_full.py --root /tmp/p0-full-new    --label new --case A --out /tmp/raw_new_A.json
$PY probe_full.py --root /tmp/p0-full-new    --label new --case B --out /tmp/raw_new_B.json
```
Каждый процесс: 1 L1 + 2 L2 (T=0.7, max_tokens=2400). Затем 9 проверок §5 по
`l2_texts` и self-echo-проверка. Ограничения те же: read-only, без Telegram,
`bot_settings` не выгружать.

## 6. Инфраструктурные находки (для следующих лейнов)

1. `graph_facts`, `lore_stories`, `chat_running_summary`, `summary_runs`,
   `mca_lessons`, `smart_messages` — SQLite, не PG (подтверждено повторно).
2. `bot_settings` (537 ключей) содержит живые ключи провайдеров: выгружать
   нельзя, читать только через реальные резолверы в памяти.
3. `/tmp` заполнен на 96% (1.1 GB): полный `rsync` прод-дерева падает на
   `backups/pre_deploy_*.db`; рабочий вариант — staging только `.py` (11.5 MB).
4. Учёт usage/событий в пробе обязательно заглушать: иначе LLM-вызовы пишут в
   PG (`llm_usage_events`, `mca_events`), что нарушает read-only.
