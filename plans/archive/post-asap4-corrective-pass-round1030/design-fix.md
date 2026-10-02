# design-fix.md — механизм embedding quota (T-4502 @Architect, corrective pass)

Feature: `post-asap4-corrective-pass` · Режим: design (docs-only) · Basis: прод 2.58.45 (HEAD `b5eaecd`) · **Risk-Level: R2** — поведение quota-пути меняется на живом проде, но внутри существующего control plane, ΔDDL=0, двойной kill-switch, rollback без даунгрейда схемы. До R3 подняло бы:touch онлайн P0-пути, ΔDDL, или парковку без верхней границы.
Входы: `rca-graphrag.md` (RCA с file:line), `requirements-map.md` R5-A-001…006, ADR-1028-7 (AM-1, D1, Sanctions).
Номера строк сверены с локальным HEAD (= прод `b5eaecd`); расхождение с RCA ±5 строк: `record_rate_limit` в `_on_error` — **:1157** (не :1160), дубль — **graphrag_rebuild.py:1292** (не :1297).

**Граница (незыблема):** фикс ТОЛЬКО внутри control plane ADR-1028-7 D1/AM-1. Второго GraphRAG/реестра/activation API нет; ротация ключей не изобретается (её объективно нет — RCA §6); FTS fail-soft неприкосновенен. Спец-файл не создаётся (решение PM), этот документ — контракт реализации для T-4503 [@Builder].

---

## D1. Kind-aware parking группы (spend/daily)

**Проблема:** `retry_after_seconds()` (embedding_control_plane.py:361–370) не видит kind → дневной spend-бюджет получает тот же 20-секундный horizon, что и burst → вечный цикл «resume → 429 → pause 20s» (RCA §2).

**Механика.** В `_on_error` (:1148–1184) точка вычисления delay (:1153) разделяется по kind:

- `kind ∈ {spend, daily}` (классификация `classify_rate_limit`, :329–358; exhausted от `is_quota_unavailable`, :373–389 — не меняется):
  - провайдер дал Retry-After → `next_allowed_at = now + min(RA, ceiling 300s)` (AM-1-политика уважения RA сохраняется);
  - RA нет (прод-кейс Gemini) → **парковка до оценки reset**: конец текущих суток UTC (`next UTC midnight`) + safety-margin `EMBED_QUOTA_RESET_MARGIN_SECONDS` (default 300s). Env-оверрайд `EMBED_QUOTA_RESET_HORIZON_SECONDS` (>0 → фиксированный горизонт, если владелец эмпирически узнает реальный reset провайдера — у Gemini он не UTC-midnight, честно это не asserting). Верхний cap `EMBED_QUOTA_PARK_MAX_SECONDS` default 86400.
  - **Честность:** `note` в `embedding_quota_state` пишется как `parked kind=spend est=utc_day_end` (отличим от точного `ra=...`); в логе `cooldown_s=<часы>`; панель показывает «парковка до T (оценка до конца суток UTC; точный reset провайдера неизвестен)». Никакой фальшивой посекундной точности.
- `kind ∈ {rpm, tpm, rate}` / burst — **без изменений**: Retry-After с ceiling 300s, нет RA → дефолт 20s (`EMBED_RATE_LIMIT_DEFAULT_COOLDOWN_SECONDS`).

**Resume не будит паркованную группу до `next_allowed_at`** — достигается СУЩЕСТВУЮЩИМИ гейтами, которые при длинном горизонте начинают работать как задумано (AM-1 §68):
- `_resume_later` (graphrag_rebuild.py:346–349): сверка `next_allowed_at` реестра, перепланирование на остаток; sleep-кап 6ч (:335) самоперепланируется — многочасовая парковка безопасна;
- `_ensure_job` (graphrag_rebuild.py:1514–1520): рестарт-гейт — «не истёк → ждём, generation НЕ сбрасывается»; именно это устраняет прод-инцидент «деплой-рестарт разбудил застрявшую джобу» (RCA §4);
- инвариант: **0 HTTP-вызовов в охлаждённую spend-группу до `next_allowed_at`, включая рестарты процесса.**
- P3-rebuild не адмитится scheduler'ом до `next_allowed_at` (§18 preemption, embedding_control_plane.py:696–700) — существующее, парковка усиливает; P0/P1 online при parked-группе получает существующий fail-soft `EmbeddingGroupCoolingDown` (:772–780).

## D2. Auto-resume backoff: нелинейный, рестарт-персистентный, отменяемый успехом

- Счётчик `quota_exhaust_streak` — число подряд exhausted-пауз джобы без успешного батча между ними.
- **Персистентность (ΔDDL=0):** `_pause_bookkeeping` (graphrag_rebuild.py:269–301) уже пишет JSON в `task_jobs.result_ref` (`pause_started_at`, `pause_count`); добавляются ключи `quota_exhaust_streak`, `quota_kind_last` (инкремент только при exhausted-классе, reason `rate_limit:quota_group`). Толерантный парсер (:278–283) — старые строки совместимы. Не в памяти → переживает рестарт.
- **Формула** (только для пауз БЕЗ parking-горизонта — kind unknown/tpm без RA; поверх parking backoff не добавляется, чтобы не наслаивать фальшивую точность на честный reset): `delay = min(default_20s × 2^streak, EMBED_RESUME_BACKOFF_MAX_SECONDS=3600) × jitter(1.00–1.25)`.
- **Отмена при успехе:** первый успешный батч после resume обнуляет `quota_exhaust_streak` в `result_ref` (одна точка в `run_job` рядом с checkpoint-записью, есть job_id и db); при spend-парковке стрик инкрементируется (диагностика/горизонт), но delay не умножается — resume строго на `next_allowed_at`.
- **Horizon 24h остаётся:** `pause_started_at` ставится однажды (:284–286) и не сбрасывается между паузами → парковка расходует общий wall-clock-горизонт `EMBED_RETRY_HORIZON_HOURS` (graphrag_rebuild.py:210–216); исчерпание → терминальный `retry_horizon_exhausted` (существующий путь :885–905). Спустя сутки+ непрерывно исчерпанной квоты джоба честно failed, оператор может переоткрыть (`retry_on_schedule`, :1534–1541).

## D3. Честная диагностика «распределять некуда»

- `build_credential_pool` (:246–292) уже владеет фактом; новый чистый helper `pool_rotation_diagnosis(pool)` → `{keys, groups, known, degenerate}` (`degenerate = не known ИЛИ |groups|==1`).
- `provider_panel()` (:1439+) добавляет блок: `rotation: none | keys: 3 | groups: [unknown] | degenerate: true` + hint: «задайте `EMBEDDING_QUOTA_GROUP_LABELS` / hot `keys.embedding_quota_group_labels` (формат `alias:group,...`) — разделение ключей по квота-группам подхватывается живьём, без рестарта» (пул строится на каждый вызов, RCA §7.6).
- Лог: WARN `embedding pool rotation=none | group=unknown | keys=3 | hint=EMBEDDING_QUOTA_GROUP_LABELS` — не чаще 1 раза / 10 мин (иначе новый шум вместо старого).
- UI-текст панели — по-русски, R17-safe (только alias/счётчики). `_pick_credential` (:1096–1108) НЕ меняется: same-group-защита §10 корректна, «фейковая ротация» не вводится.

## D4. Счётчик 429: один вызов

Точка истины — `_on_error` (embedding_control_plane.py:1157). Удалить повторный `ECP_REGISTRY.record_rate_limit()` в pause-конверсии CoolingDown (graphrag_rebuild.py:1289–1294): реальный 429 за цикл ровно один, второй вызов учитывал паузу без свежего 429. `429_last_10m` перестаёт задваиваться (59 → ~29 на проде) — метрика снова отражает интенсивность.

## D5. Kill-switches (конвенция ADR-1028-7: env-only, default ON, OFF = бит-в-бит)

| Флаг | OFF-поведение (= текущий код 2.58.45) |
|---|---|
| `EMBED_QUOTA_KIND_PARKING_ENABLED` | kind не влияет на длительность: `retry_after_seconds()` как сейчас (дефолт 20s), note/log прежнего формата |
| `EMBED_RESUME_BACKOFF_ENABLED` | задержки resume без нелинейности: дефолт-кулдаун как сейчас |

Флаги рядом с `quota_group_cooldown_enabled()` (:92–94, через `_flag` :76); float-параметры через `_settings_value` (паттерн :366–370). OFF-паритет каждой ветки — обязательный тест. Диагностика D3 под общим мастер-флагом зоны (`EMBED_CONTROL_PLANE_ENABLED`).

## D6. ΔDDL цель 0 — достигается

Новые данные живут только в: (1) `task_jobs.result_ref` — JSON-бухгалтерия (`quota_exhaust_streak`, `quota_kind_last`; `pause_started_at` уже был); (2) `embedding_quota_state` v23 — как сейчас, меняются только значения `next_allowed_at`/`note`; (3) v23-колонки реестра `pause_reason`/`next_allowed_at`/`attempts_total` — как сейчас. PG no-op. Миграция не нужна.

---

## Контракты данных (точные форматы для Builder)

**`task_jobs.result_ref` (JSON-бухгалтерия пауз) — новые ключи:**

```json
{
  "pause_started_at": 1790939628,          // существует (graphrag_rebuild.py:284–286)
  "pause_count": 163,                      // существует
  "last_pause_reason": "rate_limit:quota_group",  // существует
  "next_allowed_at": 1790939648,           // существует
  "quota_exhaust_streak": 12,              // НОВОЕ: подряд exhausted-пауз без успешного батча
  "quota_kind_last": "spend"               // НОВОЕ: kind последней quota-паузы (диагностика)
}
```

Чтение — только через существующий толерантный парсер (graphrag_rebuild.py:278–283: битый/чужой JSON → `{}`); отсутствие ключей = «стрик неизвестен, трактовать как 0» (старые строки совместимы без миграции).

**`embedding_quota_state.note` — два различимых формата:** `429 kind=spend ra=None` (точный RA/дефолт, как сейчас) vs `parked kind=spend est=utc_day_end` (оценка-парковка). Панель различает их и не выдаёт оценку за точный срок.

**`provider_panel()` — новый блок (R17-safe, только alias/счётчики):**

```json
"rotation": {
  "status": "none",             // "none" | "grouped"
  "keys": 3, "groups": ["unknown"],
  "degenerate": true,
  "hint": "Задайте EMBEDDING_QUOTA_GROUP_LABELS или hot-ключ keys.embedding_quota_group_labels (формат alias:group,...); подхватывается без рестарта"
}
```

**Логи (новые/изменённые, R17-safe):**
- WARN `embedding pool rotation=none | group=unknown | keys=3 | hint=EMBEDDING_QUOTA_GROUP_LABELS` — ≤1 раза/10 мин (in-memory rate-limit, не тест-ломающий);
- строка `embed rate limit` (:1178–1183) дополняется полем `parked=1|0` — чтобы в journald мгновенно отличать парковку от 20s-цикла.

## Failure semantics (краевые случаи)

1. **Оценка парковки промахнулась** (после конца суток UTC квота всё ещё исчерпана): цикл честно повторяется — spend-429 снова парковать на следующие сутки-оценку; resume между ними НЕ происходит (гейты §68). Фальшивого «второго шанса через 20с» нет.
2. **RA присутствует у spend/daily** (нетипично, но возможно): уважается RA с ceiling 300s (AM-1), парковка-оценка НЕ применяется — провайдер точнее нашей эвристики.
3. **`result_ref` повреждён/чужой**: парсер → `{}` → стрик=0 → delay как после первой паузы; деградация безопасная, без исключений в горячем пути.
4. **Сосуществование live-пути**: P0/P1-запрос при parked-группе получает существующий `EmbeddingGroupCoolingDown` fail-soft (:772–780, FTS fail-soft неприкосновенен); парковка удлиняет паузу, но не меняет контракт исключения (`next_allowed_at` уже несёт длинный горизонт).
5. **Пул «ожил»** (владелец задал labels): `build_credential_pool` строится на каждый вызов (RCA §7.6) → группы разделяются живьём, `rotation: grouped`, degenerate-сигнал исчезает, парковка остаётся только на реально исчерпанной группе.
6. **Оба флага OFF**: код идентичен 2.58.45 (parity-тест); единственный след новых механизмов — неактивные ключи в старых `result_ref`-строках (безвредно).

**Матрица взаимодействия флагов:** parking ON + backoff OFF → парковка работает, не-парковочные resume без нелинейности; parking OFF + backoff ON → все паузы короткие, но нелинейно растущие (×2 до 3600s) — компромиссный режим, шторм самозатухает; оба ON — основной режим; оба OFF — бит-в-бит 2.58.45.

## Наблюдаемость / верификация на проде (без фальшивых метрик)

- journald-критерий исправления: между `parked=1`-строкой и её `next_allowed_at` НЕТ пар `EMBEDDING_GENERATION_BUILD_START` + `embed rate limit` (сейчас — 148 строк/4ч); `429_last_10m` = одинарный счёт реальных 429.
- Панель `GET /api/memory/embeddings`: `next_attempt_at` уже строится из `next_allowed_at` (embedding_control_plane.py:1543–1546) — парковка отобразится автоматически; проверяется честная формулировка «оценка».
- `attempts_total` после фикса растёт ≤ числа реальных 429 (сейчас 157/ч при парковке должно остаться ≈ константе до reset).

---

## Acceptance (привязка R5-A-003/004/006)

**T-4503 [@Builder], юнит-механика:**
1. spend-429 без RA → `next_allowed_at` = конец суток UTC+margin, state=exhausted, note `parked ... est=...`; симулированный resume до срока → 0 HTTP-вызовов (мок executor).
2. рестарт не будит: `_ensure_job` при живом `next_allowed_at` → None, generation не сброшен.
3. backoff: streak 1→2→3 даёт ×2 с потолком 3600s и jitter ≤25%; перезагрузка `result_ref` сохраняет стрик; успешный батч обнуляет.
4. rpm/tpm/rate с RA → поведение бит-в-бит текущему (RA-capped 300s / 20s default).
5. degenerate-пул → панель содержит `rotation: none` + hint labels; лог не чаще 1/10мин.
6. дубль `record_rate_limit` устранён: ровно 1 инкремент на реальный 429.
7. OFF-парity обоих флагов: значения delay/next_allowed/note идентичны текущим.
8. R17: в логах/панели/нотах нет значений ключей (только alias/счётчики).

**T-4509 [@DevOps], прод-evidence:** (а) 0 повторных запросов в охлаждённую spend-группу до `next_allowed_at` (journalctl: между парковкой и reset нет пар `BUILD_START`+`embed rate limit`); (б) rebuild остаётся `paused_rate_limit` с checkpoint (processed не регрессирует от 6395); (в) после провайдерского reset — resume продолжает ту же generation (gen=1, не 2,3…) с checkpoint, прогресс растёт; (г) панель честна: `rotation: none` + hint, парковка помечена как оценка; (д) `429_last_10m` одинарный.

## Deployment / rollback

Применимость: прод `racknerd-f4e3456`, база 2.58.45; флаги default ON при деплое (Δenv=0). Rollback: soft — оба флага OFF + рестарт = поведение 2.58.45; cold — revert `b5eaecd`; новые ключи `result_ref` старым кодом игнорируются (толерантный JSON-парсер), схема не тронута — downgrade безопасен.
Вне скоупа (фиксируется честно): lease-churn retention (RCA §7.5 — парковка устраняет причину, retention-политика не в этом pass'е); расхождение статуса smart_archive (RCA §4, мелкое, отдельная задача не назначена); реальные labels групп — решение владельца (env/hot), не кода.

## Матрица «design → реализация → тест»

| Пункт | Файл:line (реализация) | Тест (tests/test_embedding_control_plane_asap4.py) |
|---|---|---|
| D1 parking-решение по kind | embedding_control_plane.py:1151–1156 (новый `_quota_parking_seconds(info)`), запись :1166–1169 | `test_parking_spend_until_utc_day_end`, `test_parking_respects_provider_ra`, `test_rpm_tpm_unchanged` |
| D1 честная note/лог/панель | :1167–1169 (note), :1178–1183 (лог), :1439+ provider_panel, :1502–1546 next_attempt_at | `test_parked_note_and_panel_honest` |
| D1 resume-гейты | graphrag_rebuild.py:346–349, :1514–1520, sleep-кап :335 | `test_resume_waits_until_next_allowed`, `test_restart_parked_not_woken` |
| D2 backoff-формула | graphrag_rebuild.py:1300–1302 + :1153 (новый `_resume_backoff_delay(streak)`) | `test_backoff_doubles_with_cap_and_jitter` |
| D2 персистентность/отмена | graphrag_rebuild.py:269–301 (+streak-ключи), сброс — точка в `run_job` у checkpoint (~:971–1010) | `test_backoff_streak_survives_reload`, `test_success_resets_streak` |
| D2 horizon 24h без изменений | graphrag_rebuild.py:210–216, :284–286, терминал :885–905 | `test_parking_consumes_horizon` |
| D3 диагностика пула | embedding_control_plane.py:246–292 (helper), :1439+ (панель), rate-limited WARN | `test_degenerate_pool_hint`, `test_diag_log_rate_limited` |
| D4 дедуп 429 | удалить graphrag_rebuild.py:1289–1294; истина — embedding_control_plane.py:1157 | `test_429_counted_once_per_real_hit` |
| D5 OFF-парity | embedding_control_plane.py:92–94 (новые флаги рядом) | `test_parking_off_bit_identical`, `test_backoff_off_bit_identical` |

## ADR

Решение фиксируется точечным AMEND в `plans/archive/asap-4-embedding-graphrag-cover-runtime-round1030/adr-1028-7-asap4-embedding-control-plane.md` (секция AMEND + строка в Sanctions) — см. этот же коммит docs.

## Трассировка требований

| Requirement | Покрытие в этом документе |
|---|---|
| R5-A-003 (а) spend-группа не ре-хитится каждые 20с | D1 + acceptance T-4503 п.1–2, T-4509 (а) |
| R5-A-003 (б) backoff нелинейный, переживает рестарт | D2 + acceptance T-4503 п.3 |
| R5-A-003 (в) ротация распределяет ЛИБО честная диагностика + labels | D3 (распределения объективно нет — RCA §6; честная диагностика + owner-опция) |
| R5-A-003 (г) P3 не сжигает квоту в ущерб online | D1 (§18 preemption по next_allowed_at — парковка усиливает) |
| R5-A-003 kill-switch / R17 | D5 + acceptance T-4503 п.7–8 |
| R5-A-004/006 (checkpoint, живые метрики) | D1-инвариант resume-гейтов + «Наблюдаемость», acceptance T-4509 (б)(в)(д) |

Владение проверками: T-4503 юниты/parity — [@Builder]; R17-скан — [@Reviewer]; прод-evidence T-4509 — [@DevOps]; финальный аудит соответствия design-fix.md — [@Reviewer].
