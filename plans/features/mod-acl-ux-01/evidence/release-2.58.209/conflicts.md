# Конфликты переноса M2.1 → `release/mod-acl-m21-2.58.209`

База: `a3262403` (2.58.208). Перенос выполнялся `git cherry-pick` по одному
коммиту в порядке линии M2.1.

## Итог

- Продуктовых конфликтов **нет**.
- Конфликтов пинов версии **нет**: M2.1-коммиты не меняют `APP_VERSION` и
  пины (старый bump `afcaf95f` в перенос не входит; версия поднята отдельным
  коммитом `e45335c2`).
- Один конфликт `modify/delete`, только в старых evidence-файлах.

## Конфликт `9b78b6ab` (test-only commit)

```
CONFLICT (modify/delete): evidence/m21/pytest-green.txt deleted in HEAD and
modified in 9b78b6ab
CONFLICT (modify/delete): evidence/m21/pytest-green.xml deleted in HEAD and
modified in 9b78b6ab
```

Причина: коммит `9b78b6ab` вместе с тестовой правкой обновлял сохранённые
артефакты прогона `evidence/m21/pytest-green.{txt,xml}`. В базе `a3262403`
каталога `evidence/m21/` нет: старые evidence M2.1 в релиз не переносятся.

Разрешение: оба файла удалены (`git rm`), тестовая правка
`tests/test_mod_acl_ux_01_m21_gates.py` применена. Перенесённый коммит:
`991caf12` (1 file, +6/−2). Это соответствует требованию «переносить только
product/test, без старых evidence».

## Проверка отсутствия продуктовых конфликтов

- `git cherry-pick` коммитов `be8e8ecf`, `def84275`, `b278a547`, `1a417917`,
  `bd92838d`, `aa130334` завершился без конфликтов (3-way merge затронул
  `bot.py`, `services/direct_chat_service.py`, `services/initiative_observer.py`,
  `services/tool_router.py`, `services/tool_schemas.py` и др.).
- 2.58.208-изменения (SMART/disk/VMQ/recent-window) сохранены: их файлы
  (`services/tool_router.py`, `services/tool_schemas.py`,
  `services/canonical_context.py`, `services/claim_envelope.py`,
  `services/runtime_probes.py`, disk/status-модули) не откатывались;
  регрессионные наборы 2.58.208 зелёные (см. `tests-2.58.209.json`).
- `deploy_v2.9.2.py` не менялся, `mca_events.py` не менялся.

## Не переносилось

- `0585f238`, `299ac2b7` и прочие docs/evidence-коммиты линии M2.1;
- `afcaf95f` (старый bump 2.58.206);
- ветка `release/mod-acl-m21-2.58.206` и evidence 2.58.206;
- `evidence/m21/*`.
