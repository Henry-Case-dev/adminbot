# REVIEW-CFG-01 — независимое ревью слайса CFG-01 (кандидат `0282fe4b`)

| Поле | Значение |
|---|---|
| Кандидат | `0282fe4b1eac02c3339586c3abab3952d6c7eae8` (8 файлов, +1057/−32), база RED-прогона `43f86ef2` |
| Входы | `evidence/cfg-01/README.md` (набор команд/статус-план), `evidence/cfg-01/red-green.txt`, `plan.md` (ADD-1), карта CFG-01 |
| Вердикт | **Approved** — реализация/поведение/эвиденс подтверждены моими прогонами; до биндинга — обязательная правка формулировки README §6 (N1) и предусловия гейта (N2, ниже); живые пункты уходят в preprod/postdeploy-проверку |

## 1. Состав и дифф — ровно 8 файлов, чужих путей нет

`plans/features/cfg/evidence/cfg-01/README.md`, `.../red-green.txt`; `services/persistent_throttling.py` (+137), `services/chat_params.py` (+80), `services/direct_chat_service.py` (+77/−…); `tests/test_direct_chat.py` (+316), `tests/test_direct_chat_concurrency.py` (+115), `tests/test_persistent_throttling.py` (+181). Изменения точечные и в духе модулей: новый резолвер в `chat_params` (без второго резолвера — тот же порядок override→hot→default, что `_resolve_from_root`), нормализация/резолв/refresh + кламп в `persistent_throttling`, один барьер и событие в `direct_chat_service`; `param_catalog.py`/`web/*` не тронуты (R1 честно вынесен в CFG-03).

## 2. Root-cause: RED→GREEN воспроизведён (мои прогоны)

- **RED (изолированный worktree `43f86ef2` + те же тестовые файлы):** `-k Cfg01` → **7 failed** (ровно те же имена: global_hot_reload, per_chat_override, refusal_reports, active_cooldown, persistent_survive_restart, parallel_burst_same_chat, parallel_burst_two_workers); `tests/test_persistent_throttling.py -k Cfg01` → **ImportError: cannot import name 'normalize_direct_chat_limits'**.
- **GREEN (кандидат):** три файла → **204 passed**; `-k Cfg01` → **7 passed** (167 deselected). Worktree удалён; живое дерево не менялось.
- **Суть фикса подтверждена эмпирически** (старый модуль из `43f86ef2` vs кандидат, один и тот же сценарий на БД): «10 израсходовано 5 → лимит стал 2» → **старый допускал ещё 5 (бонус), кандидат — ровно 2**; «окно после полного восстановления» = limit в обоих (3 и 10); «увеличение лимита» — без бонуса в обоих. Т.е. реальный исправленный дефект — **отсутствие клампа накопленного остатка** (`MIN(COALESCE(burst_left,0), ?)` в SET и WHERE; и `min(state[0], _limit)` в in-memory).

## 3. Acceptance карты (01.1–01.7, AC1–AC4, .D) — чем покрыто

- **01.1/01.2 (цепочка и hot-reload):** `test_global_hot_reload_without_restart` (MiniApp 10→2: ровно 2 обращения, 3-е — отказ до LLM; возврат 10 без рестарта), `test_refresh_*` (persistent+in-memory), `test_persistent_limits_survive_restart_with_new_values`; моя проба «старый vs новый» + `normalize`-края (0/-1/None/«10»/NaN/отрицательный cooldown).
- **01.3 (независимость слоёв):** `test_per_chat_override_isolated_and_inherit_restored`, `test_resolve_global_then_chat_then_inherit`, `test_resolve_mixed_sources_reported` (`chat/global`), fail-open `test_fail_open_on_resolver_error`.
- **01.4 (семантика):** `test_normalize_bounds`; мой прогон: `cooldown=0` → окно не ограничивает (все 5 допусков, persistent и in-memory) ✓; 0/-1→1 ✓; «без вечного лока» ✓.
- **01.5 (изоляция/параллель/рестарт/2 воркера):** `test_isolation_per_chat_and_user`, `test_parallel_burst_same_chat_obeys_limit_in_memory` (6 параллельных → ровно 2 до LLM), `test_parallel_burst_two_workers_shared_persistent_state` (2 инстанса на одной БД → суммарно 2), `test_bucket_survives_restart`; атомарность — один UPSERT (я проверил и SQL, и поведение).
- **01.6 (остаток/источник):** `test_refusal_reports_factual_remaining_and_source` (остаток 270 с, фраза «4 мин 30 сек», лог `remaining=270s … source=chat/global`, payload события ровно `{remaining_seconds:270, burst_limit:2, cooldown_seconds:300, source:chat/global}`); **мой реальный прогон события**: `emit_mca_event` + `flush_events` вставили строку в `mca_events` (stage=cooldown, reason_code=rate_limit, usage_json как ожидается; chat_id в логе маскирован) — не только мок.
- **01.7 (анти-обход):** единственная точка `throttle.allow` — в `_handle_turn` (`handle` → `_handle_turn`, проверка первым барьером до LLM/tool/дедупа); двухворкерный и параллельный тесты; команды/`edited_message` не тронуты (не были под троттлером).
- **AC3:** editing-on-cooldown (`test_active_cooldown_not_reset_by_limit_change`), reset-to-inherited, restart, TTL/NOTIFY (код: `_CACHE_TTL = 120.0`, канал `chat_params_updated`, `invalidate_chat_from_notify`; global — немедленно через ConfigCache), 2 юзера/2 чата, параллель.
- **CFG-01.D** — дефект «правка лимита не влияла без рестарта»: RED-воспроизведение на базе (§2) + фикс.
- Найденные слабые места (не дефекты, зафиксированы как N-ниже): UI-валидация границ отсутствует (R1 → CFG-03, честно задекларировано); ConfigCache — процесс-локальный (прод = один процесс; состояние троттлинга при этом в БД и общее) — при гипотетическом мультипроцессе глобальные изменения конфига в других процессах не разошлись бы без своего NOTIFY; для текущего деплоя неактуально.

## 4. Side-fix (N1) — формулировка в README не соответствует диффу (код при этом верен)

Заявлено «ветка refill подставляла `limit-1` вместо `limit` → терялся заряд окна; исправлено». По факту в коммите **refill-ветка не менялась** (`THEN ? - 1` с `? = self._limit` и в родителе, и в кандидате), и старая версия **не теряла** заряд: мой прогон на базе даёт окно = limit (3 и 10) и полное восстановление корректно. Реально исправлено другое — **отсутствие клампа** накопленных зарядов (см. §2: старый бонус +5 после «10→2»). Рекомендация: до биндинга поправить этот пункт README §6 (и не переносить формулировку «limit-1→limit» в evidence карты) — это корректировка документации, не дефект кода.

## 5. Два предсуществующих RED — подтверждены на базе

В том же базовом worktree `43f86ef2` **без кандидатных правок** (оригинальные тесты): `test_asap7_direct_settings.py::test_migration_v35_idempotent_twice` и `::test_backup_guard_fires_before_pending_step` → **2 failed** (миграции v35); на кандидате — те же 2 failed. К CFG-01 не относятся.

## 6. Blast-radius и D1

- Спот-наборы: config-слой (`test_hot_config.py`+`test_config_cache.py`) → **37 passed**; consumer'ы (`test_direct_chat_lore_inject.py`, `test_direct_chat_relations_inject.py`, `test_direct_two_call_round1022.py`, `test_soul1_w6_speech_ui.py`, `test_soul1_w5_observer_gates.py`, `test_mca08_style_form.py`) → **165 passed**.
- D1 (8 тестов переведены на конфиг-слой): в диффах тестов **не удалено ни одного assert** (единственная `-` строка — переизданный EOF-assert без изменения текста); обновления — добавление фикстуры `chat_limits`/`_limit_config` и проброс параметров; проверки усилены (лимит теперь реально привязан к конфиг-слою).

## 7. Гейт (attempt) и пригодность evidence для биндинга

`check --stage review --slice CFG-01 --candidate 0282fe4b…` → `scoped=13 errors=14` EXIT 1 (ожидаемо — pre-binding). Чего не хватает для errors=0:
1. map `candidate_commit := 0282fe4b…` (сейчас пуст → «candidate mismatch»);
2. **все 13 строк** скоупа — candidate-bound evidence (`candidate_commit`, непустые `ref`+`observation`; strict → ≥1 реальный `artifact_path`, sha желателен). README-таблица покрывает 11 строк; **нет proof-строк для `CFG-01.D` и `ADD-1.T1`** (алиас «это новая работа, не переигрывание SOUL-1» — доказательство: состав диффа кандидата/ревью);
3. **4 live-строки (01.6, AC1, AC2, AC4) помечены `live_required=True, live_when=preprod`** → гейт на review требует **VERIFIED** и evidence c `type ∈ {live, ui, provider}`; план лейна (честный RFL) при этом гейт не пройдёт. Варианты (решение PM): (а) выполнить preprod-live проверки до закрытия review-стадии; (б) переклассифицировать их в `live_when=postdeploy` (живые проверки §5 выполняются после деплоя) — тогда review допускает RFL, а release требует production-typed evidence.
4. **Пригодность `evidence/cfg-01/**`:** README (пруф-таблица и команды), `red-green.txt` (сырые сводки base-RED и candidate-GREEN) и сами тестовые файлы — реальные существующие артефакты, пригодны для `artifact_path`+`artifact_sha256`; мои независимые прогоны подтверждают их числа (7 failed на базе / 204 / 7 / 2 pre-existing).

## Итог

Код и поведение CFG-01 подтверждены независимо (RED/GREEN, инверсия клампа, семантика §01.4/§01.5, событие и лог §01.6, единственный барьер §01.7, регрессии чистые). Блокеров в реализации нет. Обязательные шаги до биндинга/гейта: исправить формулировку side-fix (N1) и закрыть пункты N2 (кандидат-привязка, 13 строк включая `.D`/`ADD-1.T1`, статусная семантика 4 live-строк).

---

# R2 — RECHECK-BIND CFG-01: **N1 закрыт; биндинг подтверждён; готов к релизному лейну**

| Поле | Значение |
|---|---|
| Коммит | `912c79b893afef4cd5df45fa91788ace0616ab6a` (evidence README 22+/10−; карта добавлена в трекинг) |
| Проверено | README-формулировки/ссылки; карта (13 строк CFG-01); гейты verbatim |

## 1. README — N1 закрыт, ссылки реальные

- §6: старая формулировка удалена; теперь — **кламп накопленного остатка** («10 доступно, 5 израсходовано, лимит 2»: база допускала ещё **+5**, кандидат — **ровно 2**; `MIN(COALESCE(burst_left,0), ?)` в SET и WHERE одного UPSERT; in-memory `min(state[0], _limit)`); refill-ветка прямо помечена как **не менявшаяся** (окно = limit на базе и кандидате).
- Grep: строка `limit-1` встречается **один раз** — только внутри дисклеймера («формулировка «limit‑1 → limit» к этому изменению не относится»); утверждения «подставляла limit-1 вместо limit» больше нет.
- §3: добавлены proof-строки `CFG-01.D` и `ADD-1.T1`; выборочная сверка: `test_global_hot_reload_without_restart` и `test_per_chat_override_isolated_and_inherit_restored` существуют в `tests/test_direct_chat.py`; `red-green.txt` и `review-cfg-01.md` существуют (мой вердикт `b5ec2339` — предок биндинга; файл tracked). Числа не подменены: RED на базе 7 failed, GREEN 204/7 — совпадают с моими прогонами (REV-CFG-01 §2).

## 2. Карта — 13 строк CFG-01 привязаны, чужие 274 не тронуты

- top: `candidate_commit=0282fe4b…`, `deployed_commit` пуст, strict+graph на месте; rows 287 = 246 items + 41 additional.
- CFG-01: **13/13 required**, у каждой candidate-bound evidence (все с `candidate_commit=0282fe4b…`); статусы: **9 VERIFIED** (01.1–01.5, 01.7, AC3, .D, ADD-1.T1) + **4 READY_FOR_LIVE** (01.6, AC1, AC2, AC4) — не VERIFIED.
- Live-строки: `live_required=True, live_when=postdeploy` + `live_note` (процесс CFG: owner/live не блокируют очередь, сценарий README §5, закрытие на postdeploy).
- Артефакты: 7 различных, **все существуют**; sha256 зафиксирован и **совпал** для 6 артефактов (README 13 записей, red-green 6, `test_direct_chat.py` 11, `test_direct_chat_concurrency.py` 3, `test_persistent_throttling.py` 10, `test_settings_worker_sync_round1018.py` 1) — спот велик, включены все требуемые.
- Прочие 274 строки: **все PENDING, без evidence** — биндинг не задел остальные слайсы.

## 3. Гейты (мой прогон, verbatim)

- `--stage plan` → `stage=plan inventory=246 manual=41 scoped=0 errors=0` **EXIT 0**;
- `--stage review --slice CFG-01 --candidate 0282fe4b1eac02c3339586c3abab3952d6c7eae8 --repo .` → `stage=review inventory=246 manual=41 scoped=13 errors=0` **EXIT 0**.

## Нит (не блокирует)

`N-R2-1`: две evidence-записи со ссылкой на `plans/features/cfg/review-cfg-01.md` — без `artifact_sha256` (у остальных шести артефактов sha есть и совпадает; гейт проходит, sha «recommended»). Рекомендация учётному лейну: добавить sha для единообразия строгой сверки.

## Готовность к релизу

Биндинг CFG-01 подтверждён; код/карта/эвиденс согласованы. Релизному лейну: изолированный релиз кандидата `0282fe4b…` → после деплоя `deployed_commit := <SHA>`; 4 RFL-строки закрываются по сценарию README §5 с production-typed evidence; затем `--stage release --candidate 0282fe4b… --deployed-commit <SHA>`.
