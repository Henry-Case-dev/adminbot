# REV-REL-258109 — независимое ревью релизного поезда 2.58.109

Вердикт: **Approved** (кандидат `a1d8bd62`, база деплоя = 2.58.108 `be60041f`) → DevOps.
Дата: 22.10.2026. Режим: read-only; гварды воспроизведены самостоятельно (venv aiogram 3.31.0).

## Состав

- Поезд `be60041f..a1d8bd62` = 4 коммита: `24aacbd9` (docs-книга 2.58.108 postdeploy — только plans/, не runtime), `77985666` FIX-INITREPLY, `1e3e5949` docs, `a1d8bd62` bump. Runtime-дельта = `services/direct_chat_service.py` (+ токен версии в `config/settings.py`); web/ и migrations — 0 файлов; ΔDDL=0 (ddl-check: периметр пуст, schema v37); чужие dirty (181) в коммиты не вошли.
- Ревью-артефакт `evidence/initreply-fix/review-initreply.md`: **Approved**, привязка к `77985666`, независимая от Builder.

## Гварды (воспроизведены, не по логам)

| Гвард | Результат |
|---|---|
| F8 `--check` | CHECK OK: реестр **582 == REGISTRY**, карта полна, R17-чисто |
| `test_asap8_initreply_binding.py` | **5 passed** (3 CONTRACT + 2 REGRESSION) |
| Related инициативные (f6+p0-init-arch+w5-vitality+w5-gates+p0-initfix+smartmodule_utils+nostalgia-ab) | 128 passed + 1 флейк-перезапуск (см. риски); Builder-лог 129p подтверждён |
| write_points (`test_mca01_tx_task_supervisor_round1027.py -k write_points`) | 1 passed, 32 deselected |
| Fingerprint | runtime `factory_set_fingerprint()` == константа `c19d35a1c093` |
| JS-unit + help-sync | 39p + 24p (совместный прогон 68 passed) |
| JS syntax sweep `node --check` | **107 файлов / 0 bad**; 4 node-пина OK (mini-lens — из лога 5/5) |
| pins24 | принят лог PKG-109: 868 passed / 0 failed, EXIT 0 (venv) |

## Фикс (код-аудит)

Резолвер `_initiative_reply_target`: fail-open тотальный (любая ошибка → WARNING с chat-id → None, отправка не блокируется), SQL параметризован, фрешность ≥ now-24ч в WHERE; reply только первому чанку (прецедент `send_chunked_reply`); 400 gone → ровно один retry без reply через переиспользованный `_is_reply_target_gone`, прочие TelegramBadRequest — re-raise (контур прежний). Ностальгия/heartbeat: `intent_row is None` → None до SQL → `send_text` без kwargs — байт-в-байт. Импорты (`TelegramBadRequest`, `time`, `json`, `row_get`) и `send_text **kwargs→bot.send_message` подтверждены. R17: в логах только chat/msg id.

## Гигиена

Секрет-скан диффа `be60041f..a1d8bd62`: **0 попаданий** (пароли/ключи/токены/private key/провайдер-префиксы/IP). BOM: базовые и кандидатские блобы `settings.py`/`README.md` идентичны (`EF BB BF`), контент после amend корректен (импорт settings → 2.58.109, F8 --check зелёный). aiosqlite-ворнинги «leaked connections» (22/7) — pre-existing тест-инфа, rc=0 при полных счётчиках, related-nonblocking.

## Риски (все NONBLOCKING)

- Флейк `test_p0_init_arch_fix_observer.py::test_new_small_chat_normal_profile_reaches_full_opportunity[20]`: 1 сбой в моём композите, 4/4 перезапуска зелёные; тест завязан на `time.time()` (граница фрешности), дифф send-пути с ним не пересекается. Pre-existing.
- Фолбэк «последнее сообщение адресата ≤24ч» может привязать reply не к семантически адресованному — задокументированный best-effort §4.1, принят планом.
- 24aacbd9 не был указан в брифе поезда (3 коммита) — docs-книга предыдущего релиза, runtime не трогает.

## Postdeploy-план (передаётся DevOps)

1. healthz → 2.58.109 после планового рестарта.
2. Blob только `services/direct_chat_service.py` (mca_vision не менялся — не нужен).
3. Реальный reply инициативных — 48ч телеметрия (наблюдение, не гейт) — соответствует PET_PROJECT-правилу.
4. Rollback: ветка `release/fix-2.58.108` = `be60041f`, создать при деплое.

## Итог

Блокеров нет. Все обязательные проверки VERIFIED на точном кандидате `a1d8bd62`; любые изменения до поезда инвалидируют evidence.
