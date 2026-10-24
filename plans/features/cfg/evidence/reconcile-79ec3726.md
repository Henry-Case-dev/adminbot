# Сверка карты CFG с прод 2.58.129 @ `79ec3726` (PM-CFG-RECONCILE)

**Дата:** 2026-10-25. **Ветка:** `pm/cfg-reconcile`. **База:** `origin/master` `24ca634b` (без reset).
**Цель сверки:** привести `plans/features/cfg/requirements-map.json` в соответствие с фактическим
продом: APP 2.58.129, серверный `git rev-parse HEAD` = `79ec3726c0919e6ffeaeb235be4f8d6326c4e12a`
(`release-258129.md` §Deploy: healthz 200, NRestarts 0, 0 ERROR/Traceback, ΔDDL 0).

**Рамки работы:** только метаданные карты и её evidence. Код, прод, SSH, другие карты,
`plans/current_task.md`, `progress_scope.json`, `workflow_state.md` не трогались.
Новые продуктовые проверки не выдумывались и не подменялись «переносом» старых.

---

## 1. Исходная точка: 553 ошибки

```
py -3 <OPENCODE_CONFIG>/tools/requirements_gate.py check --stage release \
  --map plans/features/cfg/requirements-map.json \
  --candidate 79ec3726c0919e6ffeaeb235be4f8d6326c4e12a \
  --deployed-commit 79ec3726c0919e6ffeaeb235be4f8d6326c4e12a --repo .
```

`stage=release inventory=246 manual=47 scoped=250 errors=553`, EXIT 1.

| # | Класс ошибки | Кол-во | Причина |
|---|---|---|---|
| 1 | `candidate mismatch; map candidate_commit must match --candidate` | 1 | карта стояла на `d860a529` (последняя полная проверка CFG, 2.58.104) |
| 2 | `map deployed_commit does not match actual deployment` | 1 | в карте `8ea6ed4e` (2.58.104), прод уже `79ec3726` (2.58.129) |
| 3 | `no evidence bound to reviewed candidate` | 247 | ни одна evidence-запись строки не привязана к запрошенному кандидату |
| 4 | `no candidate-bound evidence points to an existing repo artifact` | 247 | следствие п.3: список «bound» пуст, проверять артефакт нечего (strict) |
| 5 | `live requirement lacks evidence for stage release` | 57 | подмножество п.3: у строк с `live_required=true` нет bound-записи типа `live`/`production` |

**Итого:** `2 + 247 + 247 + 57 = 553`. Реальных «сломанных» требований здесь нет:
доминирует один системный факт — карта не пере-привязывалась после 2.58.104, а все 620
evidence-записей несут собственные исторические `candidate_commit` (31 разный sha, максимум
169 записей на `5af56d8b`). Класс «mandatory not VERIFIED» отсутствует: статусы
(209 VERIFIED / 35 PENDING / 2 READY_FOR_LIVE по `items`, не требуемые строки — `context`/
`duplicate`) не являются источником ошибок.

### 1.1. Состояние артефактов (не ошибки гейта, но реальные дефекты evidence)

| Проверка | Результат |
|---|---|
| `artifact_path` существует + `artifact_sha256` совпадает | **518** из 620 записей |
| `artifact_sha256` не совпадает с текущим файлом | **101** запись в **19** файлах |
| `artifact_path` отсутствует в репозитории | **1** запись |

- 101 устаревший хеш — это «живые» файлы, изменившиеся уже после записи evidence:
  `tests/test_cfg07_egress_dictionary.py` (14), `plans/features/cfg/evidence/cfg-03/audit-summary.json` (12),
  `tests/test_direct_chat.py` (11), `tests/test_cfg02a_image_quota_ui.py` (7),
  `tests/test_factcheck_planner_cfg06.py` (7), `evidence/cfg-03/inventory.json` (6), далее <6.
  Хеш фиксировал содержимое на момент проверки; он не «испорчен», а несопоставим с текущим файлом.
- 1 отсутствующий путь — `plans/features/cfg/evidence/cfg-02a/tails-r1/ui-e2e/e2e-run.log`
  (строка `CFG-02.AC1`, кандидат `db2b7044`). Файла нет ни в одном коммите:
  `git log --all -- <path>` пуст, а `.gitignore` содержит `*.log` — лог физически не мог быть
  закоммичен. Три соседних артефакта того же прогона (`ac1-desktop-1280x800.png`,
  `ac1-mobile-360x780.png`, `ac1-viewports.json`) на месте, поэтому строка не остаётся без evidence.

---

## 2. Что исправлено (только доказанные метаданные)

### 2.1. Идентичность кандидата и прода

`candidate_commit` и `deployed_commit` → `79ec3726c0919e6ffeaeb235be4f8d6326c4e12a`.

Доказательство — сам релизный артефакт `release-258129.md` §Deploy: серверный HEAD `79ec3726`
совпадает с release SHA, APP_VERSION `2.58.129`, healthz 200, NRestarts 0.

**Границы этого изменения (важно):** `candidate_commit` в схеме — идентификатор релиз-кандидата,
на котором карта подаётся на release-этап; это **не** заявление, что все строки пере-проверены на
`79ec3726`. Ни одна существующая evidence-запись не переписана: у каждой остался собственный
`candidate_commit`. Остаток ниже (245 строк) гейт показывает именно потому, что п.2.1 ничего не
маскирует. То же зафиксировано в поле `binding_note` карты.

### 2.2. Cover-style: привязка реального релизного evidence

Фикс `16a0dbbf` (Reviewer Approved) → merge `62969444` → bump `79ec3726`; выкачен на прод
(`release-258129.md`). Затронуто ровно 5 файлов, включая `services/cover_style_edit.py`
(`_extract`, `_response_diag`, `provider_meta`) и `services/cover_style_jobs.py`.

К `79ec3726` привязаны две строки, чьи acceptance-тексты действительно покрываются этим фактом:

| Строка | Новая запись | Что доказывает | Чего не доказывает (записано в observation) |
|---|---|---|---|
| `CFG-02C.3` | `release-258129.md` (type `production`) | base/styled/recovery/fallback Summary-обложки: падение в `bad_json` → fail-soft публикация Base, после фикса `_extract` разбирает бинарный 2xx/b64/url/output-конверты, ретрай не уходит сверх одной попытки; 31 passed + 1154 passed в профильном наборе | квоты, резервирование, лимиты Summary не пере-проверялись |
| `CFG-02C.6` | `cover-style-json-fix.md` (type `test`) | ретрай не размножает платные вызовы: в прод-логе ровно 2 обращения, третьего нет, стадия завершилась Base-обложкой; `provider_meta` финальной попытки сохраняется в job meta | атомарность reservation/commit/release в БД и поведение при рестартах не пере-проверялись |

Прогоны выполнены на `62969444`; `79ec3726` отличается от него только bump-пинами версии
(`release-258129.md` §Тесты/§Guard: 31 файл / 32 пина, F8-мета HEAD `62969444`, ΔDDL 0).
Это записано прямо в наблюдениях, чтобы привязка не читалась шире, чем есть.

Строки `CFG-02B.5`, `CFG-02C.2`, `CFG-02C.5`, `ADD-2.2` **не** привязаны: их acceptance про
квоты/частотный лимитер/подписи MiniApp, а cover-фикс этого не проверяет.

---

## 3. Что сознательно НЕ исправлено

### 3.1. 245 строк без привязки к `79ec3726`

Массовая перепривязка не выполнялась: между последними проверками (2.58.60…2.58.104) и 2.58.129
изменены CFG-поверхности. По `slice-graph.json` write-scope (85 путей) диф `d860a529..79ec3726`
составляет **34 файла, +6331/−797**, в том числе `web/app.js` (+635), `web/index.html` (+686),
`web/static/app.css` (+305), `services/*`, `tests/test_cfg02b_image_freq_limits.py`,
`tests/test_cfg03_param_audit.py`. Утверждать, что 245 требований «по-прежнему выполнены на
79ec3726», без их перепрогона — значит подделать evidence. Единственный корректный путь —
пере-проверка по срезам на 79ec3726 с новой привязкой.

### 3.2. 101 устаревший `artifact_sha256`

Пересчёт хеша «под текущий файл» без перепрогона приравнял бы старое наблюдение к новому
содержимому. Хеши оставлены как исторический факт; при пере-привязке срезов их нужно пересчитать
вместе с новым прогоном.

### 3.3. Отсутствующий `e2e-run.log`

Восстановить нельзя: файл никогда не коммитился (`*.log` в `.gitignore`). Строка `CFG-02.AC1`
опирается на 3 существующих артефакта того же прогона + `e2e-log.json`/`README.md`/скриншот
`83ecd202`. Это ограничение зафиксировано, а не «залечено» пустышкой.

---

## 4. Остаток после сверки

```
py -3 <OPENCODE_CONFIG>/tools/requirements_gate.py check --stage release \
  --map plans/features/cfg/requirements-map.json \
  --candidate 79ec3726c0919e6ffeaeb235be4f8d6326c4e12a \
  --deployed-commit 79ec3726c0919e6ffeaeb235be4f8d6326c4e12a --repo .
```

`stage=release inventory=246 manual=47 scoped=250 errors=547`, **EXIT 1** (сырой вывод:
`plans/features/cfg/evidence/ledger/gate-release-79ec3726.txt`).

| Класс | Было | Стало | Δ |
|---|---|---|---|
| candidate mismatch | 1 | 0 | −1 |
| deployed_commit mismatch | 1 | 0 | −1 |
| no evidence bound to reviewed candidate | 247 | 245 | −2 |
| no candidate-bound evidence points to an existing artifact | 247 | 245 | −2 |
| live requirement lacks evidence for release | 57 | 57 | 0 |
| **Всего** | **553** | **547** | **−6** |

Арифметика остатка сходится: `245 + 245 + 57 = 547`.

Остаток по срезам (required-строки без записи на `79ec3726`): CFG-06 — 98, CFG-04 — 20,
CFG-03 — 19, CFG-FINAL — 17, CFG-02B — 17, CFG-01 — 13, CFG-07B — 12, CFG-07A — 12,
CFG-07C — 12, CFG-02C — 11, CFG-02A — 9, CFG-05-Verify — 8. Всего 248; гейт проверяет 245,
потому что 3 строки имеют `verification_tier=owner_optional`
(`CFG-04D.4`, `CFG-06G.8`, `CFG-07D.1.OBS`) и по политике `plans/owner_live_checks.md`
исключены из обязательных, но остаются в карте как необязательное наблюдение владельца.

Из 245 строк **57** помечены `live_required=true` — им после перепрогона понадобится ещё и
live/production-запись на выкаченном билде.

---

## 5. Что требуется дальше и от кого

1. **Builder + Reviewer, по срезам** (CFG-01…CFG-07, CFG-FINAL): перепрогон срезовых проверок
   на `79ec3726` и привязка результатов к этому sha (245 строк, из них 57 — с live/production).
   Это продуктовая работа, а не метаданные, и в рамки сверки не входит.
2. **При пере-привязке среза** — пересчитать устаревшие `artifact_sha256` (п.3.2) и не
   восстанавливать `e2e-run.log` искусственно (п.3.3).
3. **Решений владельца не требуется:** остаток — инженерный долг карты (пере-проверка),
   а не продуктовый выбор, не креденшлы и не ручная проверка устройства.
4. CFG-02C.3/.6 при перепрогоне соответствуют политике `PET_PROJECT`: cover-style фикс уже
   выкачен во всех чатах штатным релизом, канареечных этапов не вводилось.
