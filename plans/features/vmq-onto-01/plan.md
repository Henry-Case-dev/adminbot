# VMQ-ONTO-01 — план очереди, срезов и покрытия требований

Дата планирования: 09.11.2026. Владелец плана: PM. Код не менялся.

Источники:

- эпик — `plans/owner_inputs/2026-11-09-vmq-onto-01.md` (1201 строка, sha256 в карте);
- поправка — `plans/owner_inputs/2026-11-09-vmq-qrng-provider-management.md` (30 строк, sha256 в карте);
- mapping Architect — `plans/features/vmq-onto-01/audit-head.md` (141 строка). **На момент планирования файл в рабочем дереве отсутствует** (см. §8 «Расхождения»); выводы mapping сохранены в `plans/workflow_state.md` (строка 10) и использованы как источник порядка зависимостей.

Машинные артефакты:

- `plans/features/vmq-onto-01/requirements-map.json` — 380 классифицированных строк исходника + 46 ручных требований (`strict_evidence: true`, `slice_graph_path: slice-graph.json`);
- `plans/features/vmq-onto-01/slice-graph.json` — 12 срезов, зависимости, write-scope, внешний блокер.

## 1. Место в очереди

VMQ-ONTO-01 — **один новый эпик в конце исходной очереди**, ровно в той позиции, где он уже зарегистрирован в `plans/progress_scope.json` (`vmq-onto-01`, PENDING), перед `self-diag-01`. Порядок уже исполняемых задач не меняется.

`VMQ-V` (voice → Writer) — единственное исключение: он может исполняться как **P0 corrective раньше остальных срезов эпика** при двух условиях: (1) ни один активный Builder не редактирует те же файлы (`handlers/voice_transcription.py`, `handlers/direct_chat.py`, `handlers/media_common.py`, `services/direct_context_composer.py`), (2) факт перестановки фиксируется PM с причиной. Сейчас в работе другие файлы (MEMORY-07 quality на `integ/unify-release`), поэтому условие (1) выполнимо при проверке перед запуском.

Очередь не переписывается: эпик не «встраивается» перед исполняемыми задачами, даже если его код частично готовится параллельно (провайдеры QAN — изолированные файлы).

## 2. Порядок зависимостей (граф, не FIFO)

```
VMQ-A (mapping, done)
 ├─ VMQ-V  (P0 corrective voice)
 ├─ VMQ-ONTO-A ─ VMQ-ONTO-B ─┐
 │      └─ VMQ-M1 ───────────┴─ VMQ-M2 (unified retrieval, ONTO-C/D внутри)
 └─ VMQ-Q0 ─ VMQ-Q0-IBM ─────────────┐
                                     └─ VMQ-Q1 (шесть consumer-интеграций)
VMQ-Q0-IBM ─ VMQ-O ─ VMQ-U ─ VMQ-R (release gate)
VMQ-V, VMQ-M2, VMQ-Q1, VMQ-O, VMQ-U ─ VMQ-R
```

Явно зафиксированные serial-join’ы (это зависимости, а не пожелания):

| Зависимость | Причина |
|---|---|
| `VMQ-M2 → VMQ-V` | общий файл `services/direct_context_composer.py`: сначала доставка голоса, потом retrieval bundle |
| `VMQ-M2 → VMQ-M1`, `VMQ-ONTO-B → VMQ-ONTO-A` | производные контракты и `services/database.py` (миграции/индексы) пишутся последовательно |
| `VMQ-Q0-IBM → VMQ-Q0` | общий `services/mca_random_source.py` |
| `VMQ-Q1 → VMQ-M2 + VMQ-Q0-IBM` | потребителям нужен и evidence-bundle, и рабочий RandomSource/IBM-пул |
| `VMQ-U → VMQ-O` | виджеты читают агрегаты, а не сырые моки |

## 3. Срезы, владельцы и покрытие

| Срез | Владелец | Требования | Риск | Наблюдаемый исход |
|---|---|---|---|---|
| VMQ-A | Architect (сделано), Reviewer/PM приёмка | VMQ-A-01 | R0 | дельта-карта HEAD/MEMORY/очередь + контракт событий и fixtures |
| VMQ-V | Builder + Reviewer | V-01..V-04 | R1 | запрошенный ready-транскрипт реально в Writer payload, без дублей и ложного «не вижу» |
| VMQ-ONTO-A | Architect + Builder | O-01, O-02 | R1 | typed смыслы user/topic/event/fact и разрешение неоднозначности |
| VMQ-ONTO-B | Builder | O-03 | R1 | typed relations с provenance, legacy не подтверждён |
| VMQ-M1 | Builder | M-01..M-03 | R2 | эпизоды по Reply-ветке, многолетние темы, инкрементальное версионируемое досье |
| VMQ-M2 | Builder + Architect | M-04, M-05, O-04 | R2 | один unified retrieval: person overview/temporal + bundle, без mass reembedding |
| VMQ-Q0 | Builder + Architect | Q-01, Q-02, Q-07, Q-08, QM-01..QM-06, QM-09 | R2 | один RandomSource, 4 провайдера, настройки/секреты/live-apply, честная диагностика, поле без bias |
| VMQ-Q0-IBM | Builder | Q-03..Q-06, QM-07, QM-08 | R3 | demand-first, adaptive wait, отдельный IBM-пул, чистота тракта, replay |
| VMQ-Q1 | Builder | I-01..I-06, Q-09 | R2 | шесть e2e-следов «eligible → influenced → module → persisted/published» |
| VMQ-O | Builder | S-01..S-03 | R2 | измеренный health, IBM quota/jobs/pool, воронка со знаменателями |
| VMQ-U | Builder + UI acceptance | U-01, U-02 | R2 | «Статус»/«Аналитика» на живых данных, desktop/mobile |
| VMQ-R | Reviewer + DevOps + PM | R-01..R-04 | R1 | default-ON effective, baseline vs new, DevOps-манифест, честное закрытие |

Всего: **47 обязательных строк** (37 из реестра §14 + 9 поправки + VMQ-A-01), 12 срезов, 380 строк исходника классифицированы.

Список `slices` в графе содержит ровно те срезы, что владеют строками карты; каждая строка имеет одного владельца.

### Параллельные полосы (по умолчанию не более 3 писателей)

- `L1` foundation: VMQ-A → VMQ-V → VMQ-ONTO-A → VMQ-ONTO-B;
- `L2` memory: VMQ-M1 → VMQ-M2;
- `L3` quantum: VMQ-Q0 → VMQ-Q0-IBM (изолированные файлы, может идти параллельно памяти);
- join: VMQ-Q1 → VMQ-O → VMQ-U → VMQ-R.

Параллельно допустимы, например, `VMQ-V` + `VMQ-M1` + `VMQ-Q0` (файлы не пересекаются). `VMQ-ONTO-B` нельзя ставить одновременно с `VMQ-ONTO-A` (общий `services/semantic_contracts.py`).

## 4. Сериализованные файлы и пересечения

Сериализуются (в графе это выражено зависимостями, не «договорённостью»):

- `services/database.py` — VMQ-M1, затем VMQ-M2;
- `services/mca_random_source.py` — VMQ-Q0, затем VMQ-Q0-IBM;
- `services/direct_context_composer.py` — VMQ-V, затем VMQ-M2;
- `web/app.js`, `web/index.html`, `handlers/web.py` — VMQ-Q0 (настройки провайдеров), затем VMQ-U (виджеты);
- `services/mca_dream_random.py` — VMQ-Q0, затем VMQ-Q1.

Найденные при сверке риски (не блокируют план, но обязательны для Builder):

1. `services/database.py` **уже изменён в рабочем дереве** (незакоммиченный diff вне этого плана). Любой из VMQ-M1/M2 обязан сначала выяснить происхождение этого diff и не затирать чужие правки.
2. Ветки MEMORY-07/08 (`integ/unify-release`, `memory-05-attribution`) правят `services/memory_*` и `services/database.py`; до их merge нельзя стартовать VMQ-M1 на тех же файлах.
3. Активные worktree `memory-cognitive-02-*` — источник правок памяти; пересечение сценариев подтверждено отчётом Architect (MEMORY-07/08 share files).
4. В корне висят неотслеживаемые `.playwright-mcp/`, `OPENCODE_WORKFLOW_SCRATCH/`, `.tmp_head.json`, `_upd.py`, `b64.txt` — это не наши артефакты, не трогаем.

## 5. MEMORY-06/07/08 и правило default-OFF

Строки MEMORY-06/07/08 **не дублируются** в этой карте: они остаются в `plans/features/memory-cognitive-02/requirements-map.json`. VMQ-M1/M2 ссылаются на них как на внешнюю зависимость (контракты, эпизоды, communities).

**Корректировка MEMORY-07 (default-OFF `MCA_MEMORY_COMMUNITIES_ENABLED`, 99.87 % legacy, нейтральные подписи, пары узлов) остаётся внутри MEMORY-эпика** и не переносится в VMQ-builder — прямое требование ТЗ §16.4 и §12.4. VMQ не создаёт второй graph store и не «включает флаг» вместо исправления причины.

## 6. Внешний блокер IBM — честно и точно

`Q-04` и `QM-08` требуют реального IBM Quantum hardware: токен/instance владельца и доступной квоты Open Plan (очередь QPU внешняя и может идти дольше измерения).

- Статус: `PENDING` + `blocked_external: true` + `external_dependency` в карте. Схема gate не содержит состояния `BLOCKED_EXTERNAL`, поэтому оно выражено явно полями, а не подменой статуса.
- `VERIFIED` на симуляторе, `quasi_dists`, сухих прогонах или «успешном account check» **запрещён**.
- Остальное реализуемо и проверяемо сейчас: ANU/LfDR/Lizaonair адаптеры, реестр и настройки, маскированные секреты, live-apply, health/диагностика, failover, отдельный IBM-пул и job-lifecycle на фейках API, отсутствие PRNG/seed-expansion в IBM-тракте, replay, `unconfigured` без блокировки других источников.
- Релиз VMQ обязан показывать IBM как `unconfigured/blocked_external` и не выдавать эпик за полностью завершённый (R-03).

## 7. Поправка о провайдерах (QRNG provider management)

9 требований встроены в существующие срезы, отдельного модуля настроек/секретов нет:

- `QM-01` динамические поля по провайдеру, без ручных правок `.env` → VMQ-Q0;
- `QM-02` маскированные секреты, замена/удаление, маска не перезаписывает значение, нет открытого текста во frontend/API/логах → VMQ-Q0;
- `QM-03` live-apply и рестарт, смена/удаление ключа, смена провайдера, авто-fallback, сохранность старых значений → VMQ-Q0;
- `QM-04` честные статусы + реальная кнопка «Проверить подключение» (время, задержка, причина), без фиктивных зелёных → VMQ-Q0;
- `QM-05` сверка официальной документации провайдеров (со ссылками и датой) → VMQ-Q0;
- `QM-06` протокол запроса реквизитов у владельца (пошагово, без секретов в чате) → VMQ-Q0;
- `QM-07` приёмка реальными запросами по всем настроенным провайдерам и отказам ключей → VMQ-Q0-IBM (join-приёмка);
- `QM-08` IBM job/queue/pool → VMQ-Q0-IBM (blocked_external);
- `QM-09` `unconfigured` не блокирует остальных, заводское ON без перезаписи пользовательских значений → VMQ-Q0.

Провенанс: `source_line` каждой QM-строки указывает на нормативную строку эпика (одному source нельзя иметь два файла), точный адрес поправки — в `amendment_ref` (`...qrng-provider-management.md#L9…#L23`) и `amendment_excerpt`; sha256 файла поправки зафиксирован в карте.

## 8. Расхождения, требующие действия (не выдумываем факты)

1. **`plans/features/vmq-onto-01/audit-head.md` отсутствует** в рабочем дереве, хотя `plans/workflow_state.md` (строка 10) и задание ссылаются на него как на готовые 141 строку с классификацией «VMQ READY FOR PM LEDGER». Каталог `plans/features/vmq-onto-01/` до этого плана не существовал, файла нет и в `git status`. Выводы mapping (voice без статуса/ревизии; отсутствие резолва соседних голосовых; существующий unified retrieve пригоден; онтология ложится проекцией; квант есть только ANU, qiskit/numpy не установлены, нет IBM pool/job lifecycle; в админке есть маска секрета ANU, но нет селектора провайдеров и apply-without-restart) сохранены в workflow_state и использованы здесь. Действие: Architect обязан восстановить `audit-head.md` как evidence для `VMQ-A-01`; до этого `VMQ-A-01` = PENDING, а его ожидаемый артефакт указывает на отсутствующий файл.
2. `plans/features/self-diag-01/` также ещё не создан (другой Architect пишет `d0-discovery.md`) — не наша зона, не трогаем.
3. `services/database.py` имеет незакоммиченные изменения — см. §4.

## 9. Шлюз плана — точная команда и результат

```
cd C:\Code\Python\adminbot
py C:\Users\main\.config\opencode\tools\requirements_gate.py check --map plans/features/vmq-onto-01/requirements-map.json --stage plan
```

Результат:

```
stage=plan inventory=380 manual=46 scoped=0 errors=0
```

Проверено шлюзом: все 380 извлечённых строк исходника присутствуют и совпадают по хешу, 46 ручных строк имеют реальные `source_line`/`source_text_sha256`/`source_excerpt`, у каждой обязательной строки есть `req_id`, один владелец-срез, наблюдаемая приёмка, `live_required/live_when`, допустимый статус; граф без циклов, все владельцы имеют узлы, одновременные write-scope не пересекаются.

Дополнительно (ручная обратная сверка исходника):

- реестр §14: V-01..V-04 (4), M-01..M-05 (5), O-01..O-04 (4), Q-01..Q-09 (9), I-01..I-06 (6), S-01..S-03 (3), U-01..U-02 (2), R-01..R-04 (4) = **37/37**;
- поправка: 9/9 обязательств (поля по провайдеру, маскировка без перезаписи, live-apply/рестарт, честная диагностика с кнопкой, официальные доки, запрос реквизитов, реальные запросы с IBM job/queue/pool, unconfigured не блокирует, никакого параллельного модуля);
- 379 прочих строк классифицированы как `context` с указанием раздела и строк реестра, которые забирают их нормативную силу; ни одна строка не оставлена `unassigned` и ни одна не спрятана в «остаточный бэклог».

Ограничение шлюза: он не доказывает семантическую полноту. Поэтому §15 (корнер-кейсы) разобран адресно: race STT → V-04, bit ranges/рестарт → Q-05, чистота IBM → Q-06, unconfigured → QM-09, знаменатели/retention → S-03, доступ/секреты → QM-02/S-01, n=1/аномальные ячейки → Q-07/Q-08.

## 10. Следующий исполняемый элемент

**VMQ-V** — voice P0 corrective. Владелец: Builder. Зависимость: VMQ-A mapping (готов по содержанию, файл требует восстановления — не блокирует файлы голоса).

Условия запуска: ни один активный Builder не держит `handlers/voice_transcription.py`, `handlers/direct_chat.py`, `handlers/media_common.py`, `services/direct_context_composer.py`; перед стартом — `git status` этих файлов и согласование с текущими ветками MEMORY.

Ожидаемое evidence: `plans/features/vmq-onto-01/evidence/vmq-v/` — source-revision row, media-group payload для 2-3 голосовых, captured Writer payload, race/restart fixture + живой аналог. Затем независимый Reviewer (три опоры: реализация, валидность тестов, собственный контрпример), затем обычный релиз.

Параллельно, без пересечения файлов, можно готовить **VMQ-Q0** (провайдерный backend) и **VMQ-M1** (эпизоды) — после проверки веток MEMORY на `services/database.py`.

## 11. Что остаётся открытым

- Восстановление `audit-head.md` (Architect) — единственный пробел в провенансе плана.
- IBM credentials/quota (владелец, по протоколу QM-06) — внешний блокер `Q-04`/`QM-08`, не блокирует остальных.
- Merge MEMORY-07/08 перед VMQ-M1 на общих файлах.
- `owner_optional` строк в карте нет: все 47 строк — обязательная инженерная приёмка; ослаблять их нельзя.
