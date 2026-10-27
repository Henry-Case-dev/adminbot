# REVIEW W2 — p0-nostalgia-rework (NOST-05/06/08/09/10/11/12) — 28.10.2026

Вердикт: **NEEDS FIXES** (1 блокер, малый и механический; поведенческих блокеров нет).

Кандидат кода: `58b9f5e248f2cc0dabef94375940dc11155d8773` (детач-ворктри
`C:\Code\Python\adminbot-wt-nost2-rev`); карта/evidence биндинги — тип ветки `2bf72471`
(sha256_12 w2.md = `5999269856c4` — подтверждён по сырому блобу git). База W1 `3ea0e9f9`
— предок (`merge-base --is-ancestor` = yes), W1-поведение не откатывалось.

## Таблица по требованиям

| Требование | Статус | Ключевые доказательства |
|---|---|---|
| NOST-05 интересность (объём ≠ интересность) | VERIFIED | `_YEAR_BACK_WEIGHT`/вес происхождения снят (`nostalgia_worker.py:1125-1147,1518-1525`); `_rank_episodes` без счётчика сообщений (только topical/-year); порог — только для golden (`:935-936`); канон «Оценивай содержание, а не объём» в обоих активных канонах (`nostalgia_prompts.py:145,207`); тесты `test_volume_does_not_rank_or_drop_episodes`, `test_rank_key_has_no_volume_term`. Не словник: оценка — вердикт LLM. |
| NOST-06 вся история | VERIFIED | Тематический режим `_thematic_episodes` (`worker:1281-1363`) на существующих `search_messages_fts`+`build_fts_query`, реконструкция тем же `_episode_around` (второго движка нет); календарный приоритет НЕ гарантирован — порядок предъявления технический, финал за вердиктом (`test_calendar_not_guaranteed_over_thematic`, T17); дедуп `_episodes_dedup`. |
| NOST-08 повторы/разнообразие/без искусственной новизны | VERIFIED | Идентичность = first/last `message_key`+границы+год (`_episode_identity:452`), не текст (`test_identity_is_keys_not_text`); журнал `recent_nostalgia_sent` (30д/10sent) → `_filter_repeats`; все-повторы → skip reason=repeat, LLM даже не зовётся (`test_same_episode_not_republished`) — искусственной новизны нет; `SAY <№>` — детерминированный протокольный суффикс (`_SAY_SLOT_RE`), не речевой шаблон; разнообразие без квот (`test_diversity_across_ticks_no_quota`). |
| NOST-09 естественная реплика / 9.1 инструкции / 9.2 лимиты | VERIFIED | Активные каноны (144-150, 206-212) без «обычно 1-2 короткими фразами "кстати…"» и без `{max_words}`; `{max_words}`/`_MAX_WORDS`/`_DEFAULT_MAX_WORDS` в рабочем пути отсутствуют — остатки только в PREV_*_W1-слепках (тест-пины байт-в-байт, в LLM не едут) и комментариях; единственный слот длины — пользовательская `NOSTALGIA_MAX_SEND_CHARS` (`worker:989-992`, hot, каталог `param_catalog.py:2393`); lore/Personality Core/NO_META не тронуты (дифф 13 файлов их не содержит). |
| NOST-10 Decision Making reuse | VERIFIED | `_delegate_initiative` → `handle_initiative` бит-в-байт W1 (`worker:1073-1099`); единый send-путь (`test_delegation_single_send_path`: initiative=1, bot=0); `chain_allowed("nostalgia_due")`=True не менялся; второго роутера нет. |
| NOST-11 большой архив | VERIFIED | select-then-detail: семена ≤12 → детализация ≤2 (`_THEMATIC_DETAIL_MAX`), `test_thematic_select_then_detail_bounded`; стратификация плотных окон ≤8 страт (`_fetch_window_stratified`, `count_chat_history_messages` с тем же фильтром, `database.py:10102-10115`), `test_dense_window_stratified_coverage` + `test_sparse_window_unstratified` (W1-поведение цел); честные `truncated`/`thematic_error`/`archive_error` (`test_thematic_source_error_degrades_honestly`, `test_archive_bounds_error_honest`); `_EPISODES_MAX=4` — кап предъявления ПОСЛЕ ранжирования с честными `episodes_found/shown` в meta и UI (не квота отбора; канон счётчиков не упоминает). |
| NOST-12 админка | FAILED (артефакты) / ядро VERIFIED | `NOSTALGIA_HISTORY_DEPTH_YEARS` (settings:3340, дефолт 0 = весь архив, hot-ключ `memory.nostalgia_history_depth_years`, `test_depth_knobs_limit_years`); 17 legacy-настроек на месте (`test_admin_knobs_present`); диагностика фактического прогона в meta (`test_run_diagnostics_meta_full`) + аддитивная строка UI (`web/index.html:4514-4519`, честные ошибки/повторы/годы). **Но** реестровые артефакты не перегенерированы — см. блокер. |
| NOST-15/16 (приёмочные грани) | честный REVIEW | Карта на 2bf72471: 2 строки REVIEW (живой LLM вне моков) — не маскируются под VERIFIED; механика T16-T23/инвариантность покрыта моками. |

## Прогоны (в ворктри на 58b9f5e2)

- `py -3 -m compileall services` — exit 0.
- `py -3 -m pytest tests/test_nostalgia_w2.py -q` — **26 passed**.
- Ностальгия+смежные (список W2-доказательства §9): test_nostalgia_worker, test_nostalgia_prompts,
  test_nostalgia_corrective_r1, test_nostalgia_revamp_round1015, test_nostalgia_layer_a,
  test_smoke_round1016_nostalgia_persona, test_p0_followup_nostalgia_ab,
  test_nostalgia_history_rework, test_nostalgia_w2, test_asap5_integration_w3,
  test_expression_isolation_followup, test_prompt_migrations, test_database,
  test_asap_speech_r3b_canon, mca09 block_e+off_parity, test_soul1_w4_authorial_genre,
  test_memory_core_round1020, test_cfg07_backstage_contract, test_feature_gates,
  test_mca17_sleep_memory_workers_round1050 — **626 passed** (клейм билдера воспроизведён 1-в-1).
- `py -3 tools/gen_param_registry_round1025.py --check` — **FAIL на кандидате** (см. блокер);
  на W1-типе `fe891402` (временный детач-ворктри, удалён после проверки) — **CHECK OK (587)**.

## Блокеры

1. **[BLOCKER, малый] Реестровые артефакты не перегенерированы под новый параметр** —
   требование: сопровождение реестра параметров (R17 «ни один параметр не остался без нового
   места»); запуск из RUN-листа ревью.
   - Наблюдение: `CHECK FAILED: TSV расходится с каталогом; screen-map расходится; параметры
     без нового места: 1 (memory.nostalgia_history_depth_years)`. На W1-базе тот же чек — OK.
   - Причина: W2 добавил `NOSTALGIA_HISTORY_DEPTH_YEARS` в `param_catalog.py`/`settings.py`,
     но не перегенерировал `plans/docs/param-registry-round1025.tsv`,
     `plans/docs/screen-map-round1025.md`, `plans/docs/param-registry-round1025.meta.md`.
   - Влияние: состояние репо не проходит штатный консистент-гейт; счётчики 588/467 в коде
     верны (пины зелёные), расхождение только в производных артефактах.
   - Исправление (Builder, механическое): выполнить `py -3 tools/gen_param_registry_round1025.py`
     на кандидате и закоммитить 3 артефакта (проверено: дельта чисто аддитивная — ровно 1 новая
     строка `memory.nostalgia_history_depth_years` + обновлённые описания
     aggressiveness/year_back_days_window; случайных изменений параметров нет).
   - Репроверка: `py -3 tools/gen_param_registry_round1025.py --check` → CHECK OK (588).

## Не-блокирующие наблюдения (бэклог, один раз)

- `meta.path` пишется только на initiative-пути; legacy direct-send (K1/K3 OFF, не прод-дефолт)
  различим по отсутствию `path` — для полноты NOST-12 можно писать `"path": "direct"` (1 строка).
- `_same_episode` требует равенства года для пересечения диапазонов: эпизод через Новый год
  (валиден по W1) может повторно всплыть при перепривязке к следующему году в пределах
  30-дневного окна повторов. Редкий случай, направление консервативное (годовщина = новый
  календарный повод); зафиксировать в бэклоге.
- `_told_identities` fail-open: недоступность журнала → повторы не проверяются (честный WARNING).

## Итог для оркестратора

Behavior-часть W2 подтверждена (код, тесты 626/26, owner-guards: квот инструкций нет —
наоборот удалена скрытая; шаблонов нет; повтор-контроль по идентичности; один send-путь;
поэтапность/стратификация; админ-глубина factory-safe). Перед ревью-апрувом слайса Builder
должен выполнить блокер 1 (регенерация 3 артефактов реестра) + повторный `--check`; полный
повторный прогон тестов не требуется (изменение не затрагивает код). После этого — повторное
лёгкое ревью только по артефактам.
