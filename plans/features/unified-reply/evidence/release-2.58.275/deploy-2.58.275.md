# Release 2.58.275 — deploy (DEPLOYED_AND_VERIFIED)

- **Дата:** 2026-11-29 (UTC-записи прода: 2026-11-28T14:29Z)
- **Целевой хост:** `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot`
- **Задеплоено:** `release/2.58.275` tip **`8daef97c8`**, tree `087b8888614fff3b3fb6f4027f66230d193fd579`, **version 2.58.275**
  (собранный код/версия — `5c16e8e73`, tree `260358d8e`; разница `5c16e8e73..8daef97c8` — только 5 файлов
  `plans/features/unified-reply/evidence/release-2.58.275/**`, продуктовые байты идентичны)
- **Предыдущий прод:** `731a7e51c` = 2.58.274 (rollback-цель)
- **Изменение продукта:** P0T-REPLY-01 — смысловая цель reply в Direct (только `delivery=reply` + валидная цель)
  и канон L1 R3→R4 (`l1-planner-delivery-scope`, sha12 `64a80fb8c4ff`, factory set `1c03efc3e98b`).
- **Остальное:** test-contracts (barriers/UR-B/VMQ Q-01/Q-08) + evidence.

## 1. Кандидат и закрытие predeploy-блокеров

| # | ветка | tip | вердикт | merge |
|---|-------|-----|---------|-------|
| 1 | `feat/p0t-reply-01-2026-11-28` | `1353a5131` (код `cb387ee88`) | r1 `APPROVED_FOR_RELEASE_PREPARATION` | `6c3fcb254` |
| 1b | то же, corrective F-275-01/02 | `65607f1a7` | **r2 `APPROVED_FOR_RELEASE_PREPARATION`** (адресное ре-ревью; артефакт ревьюера `review-r2.md` добавлен в `p0t-reply-01-2026-11-28/` без изменений) | `5c16e8e73` |
| 2 | `fix/release-test-barriers-2026-11-28` | `db5d1bc66` (код `69096c451`) | r4 `APPROVED_FOR_RELEASE_PREPARATION` | `23dff2ac7` |
| 3 | `feat/ur-b-testonly-2026-11-28` | `43646c6cb` | r2 `APPROVED_FOR_RELEASE_PREPARATION` | `5cd90cb60` |
| 4 | `feat/vmq-q0-2026-11-28` | `f032216d8` (код `0d4191227`) | r2 `APPROVED_FOR_RELEASE_PREPARATION` | `d438adeff` |

- Merge `65607f1a7` — clean, добавил **только** `tests/test_direct_l1_corrective_r1.py`,
  `tests/test_rlr_proof_restart.py` и 2 evidence-файла; продукт `cb387ee88` и scope P0T побайтово идентичны
  (`raw/manifest-predeploy.txt: p0t_scope_identical_to_candidate=True`).
- Predeploy-блокеры F-275-01/02 из первого прогона закрыты: целевые тесты **2 passed**,
  `test_direct_l1_corrective_r1.py` **11 passed / 1 предсуществующий** (`bot_replies_caps`, красный и на 2.58.274),
  `test_rlr_proof_restart.py` **4 passed**, P0T suite **16 passed**, direct-батч **23 failed / 906 passed == базе**
  (0 candidate-only), version-контракт 207 passed / 1 предсуществующий, collect-only 23858.

## 2. Деплой (одна SSH-сессия; перед ней — только HTTP healthz и один `bash -n` recon)

`raw/deploy-run.txt` (полный прогон), `raw/_deploy.sh` (скрипт), `raw/deploy-recon.txt` (syntax-проверка).

```
PRE_HEAD=731a7e51cdb747fb3c0507ec80b885e4217766b0 PRE_VER=2.58.274 PRE_UNIT=active NRESTS=0
REMOTE_SHA=8daef97c86307327d93a932de9cb2e6f11f1dbb2
NEW_HEAD=8daef97c86307327d93a932de9cb2e6f11f1dbb2 REF=refs/heads/release/2.58.275
NEW_TREE=087b8888614fff3b3fb6f4027f66230d193fd579  POST_CHECKOUT_DIRTY_TRACKED=0
SETTINGS_MATCH/PROMPTS_MATCH/DCS_MATCH/L1_MATCH/MIGR_MATCH/REGISTRY_MATCH/ROUTES_MATCH/APPJS_MATCH/INDEX_MATCH = yes (все 9)
MANIFEST={"deployed_sha":"8daef97c8…","previous_sha":"731a7e51c…","previous_version":"2.58.274","release_branch":"release/2.58.275","version":"2.58.275","dirty_tracked":false,"effect":"deploy"}
LOCAL_HEALTHZ_HTTP=200  LOCAL_HEALTHZ={"status":"ok","version":"2.58.275"}
PUBLIC_HEALTHZ_HTTP=200 PUBLIC_HEALTHZ={"status":"ok","version":"2.58.275"}
UNIT=active NRESTS=0 MAINPID=1397601 BOTPROCS=1
VER_AST=2.58.275 VER_IMPORT=2.58.275 VER_MANIFEST=2.58.275
FINAL: HEAD=8daef97c8 REF=refs/heads/release/2.58.275 TREE=087b8888 DIRTY_TRACKED=0 WORKTREES=1 TMP_LEFTOVERS=0
```

Фактические sha256 на проде совпали с локальными (полный список — `raw/deploy-run.txt`, локальные — `raw/local-sha256.txt`).
`web/api/routes.py`, `web/app.js`, `web/index.html` побайтово равны 2.58.274 (маршруты и Mini App не менялись).
Схема: `PRAGMA user_version=50` до и после, `PRAGMA quick_check=ok` (277 s), DDL в релизе нет.

## 3. Effective-канон в проде (после рестарта, read-only)

`raw/deploy-run.txt` (§ EFFECTIVE CANON) + `raw/deploy-postcheck2.txt` (§ STORED CANON vs CODE CANON):

```
CANON_SEAL_INTEGRITY={}                       CANON_FACTORY_SET=1c03efc3e98b CONST=1c03efc3e98b
CANON_SHA12_ACTIVE=64a80fb8c4ff LEN=21617     CANON_R4_PRESENT=True
CANON_R3_SECTION_PRESENT=False                CANON_R3_INITIATIVE_NARROWING_PRESENT=False
CANON_R4_TRIGGER_SOURCE_PHRASE=True           CANON_IS_KNOWN=True
DB_SHA12=64a80fb8c4ff CODE_SHA12=64a80fb8c4ff DB_EQUALS_CODE=True
DB_HAS_R4_PHRASE=True  DB_HAS_R3_INITIATIVE_NARROWING=False
```

Канон в коде **и** в применённой настройке `prompts.direct_l1_planner_system_prompt` — новый R4; миграция
`R3→R4` применилась на старте (единственная изменённая строка `bot_settings`, см. §4).

## 4. Настройки/промпты: что «изменилось» и почему это ожидаемо

| показатель | pre | post |
|------------|-----|------|
| `SETTINGS_ROWS` | 558 | **558** (не изменилось) |
| `PROMPTS_KEYS` / пустых | 29 / 0 | **29 / 0** |
| `SETTINGS_MAXUPD` | 2026-11-27 21:48:55 | **2026-11-28 14:29:17** |
| `SETTINGS_MD5_KV` | 6f6d6624… | **869c711b…** |

Изменилась ровно **одна** строка — `prompts.direct_l1_planner_system_prompt` (cat=prompts), значение обновлено
штатной миграцией канона R3→R4 на старте (`raw/deploy-postcheck.txt`, §SETTINGS ROWS CHANGED AT RESTART:
`CHANGED_ROWS=1`). Это целевой эффект релиза, а не побочная правка конфигурации: пользовательские настройки,
чатовые override и остальные 28 промптов не тронуты, пустых промптов 0.

## 5. Журнал, диск, откат

- Журнал (первое окно 5 s и после settle 6 мин, `raw/deploy-run.txt`): `J_CRITICAL=0`, `J_SQL_ERR=0`,
  `J_402_403=0`, `J2_SQL_ERR=0`, `J2_CRITICAL=0`, `J2_402_403=0`; `J2_TRACEBACK=1`.
  Единственный traceback — **внешний LLM-обрыв** в инициативном обсервере:
  `services.llm_client.LLMBadResponseError: chat/completions: no final text | kind=truncated_reasoning | finish_reason=length`
  (WARNING `[b01] opportunity eval failed`, сервис продолжил работу). Не связан с релизом: за 24 ч **до** выката
  таких же `truncated_reasoning` было **76**, `opportunity eval failed` — **20**; после выката — 1 и 1
  (`raw/deploy-postcheck2.txt`). `DIRECT_ERRORS=0`, логов недоступной reply-цели (`reply target unavailable`) — 0.
- Откат: dry-run на `731a7e51c` — **`RB_RC=0`**, манифест эффекта `rollback` с version 2.58.274
  (`RB_VERSION` пуст из-за BOM в `config/settings.py` той ревизии — косметика скрипта, как и в 2.58.274;
  на rc не влияет). Временный worktree удалён: `RB_WORKTREE_LEFT=0`, `WORKTREES=1`.
- Диск: `43G` свободно до и после (54%). `disk audit` и `disk cleanup --apply` выполнены:
  `deleted=0 bytes_freed=0` — путь retention уже в норме (ровно 2 deploy-бэкапа keep=2, ничего лишнего).
  Собственных временных файлов на проде не осталось (`TMP_LEFTOVERS=0`).

## 6. Что НЕ проверено

- Живой выбор цели reply моделью в реальном много-медиа ходе: недетерминизм LLM, синтетикой не форсировался.
  Наблюдение — при естественном использовании; не блокирует (строка `live_required=false`).
- Миграция применена по факту одной строки промпта; отдельной проверки «до/после» для всех чатовых override
  не делалось, т.к. их число не изменилось (29/0) и затрагивается только глобальный ключ канона.
