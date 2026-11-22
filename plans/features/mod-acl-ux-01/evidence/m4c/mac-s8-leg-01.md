# MAC-S8-LEG-01 — legacy endpoint inventory

- **Статус evidence:** read-only инвентарь создан; legacy **не удалялся**.
- `tools/acl_legacy_inventory.py`: разбор `@api_router/@access_router/
  @chat_lore_router/@memory_router`, guard'ов (`requires_permission`,
  `requires_global_admin`, inline `is_global_admin`, `can_edit_param`,
  `can_view_key_value`, `is_dm_owner`), diff с `known_sections()/ACTION_IDS/
  known_param_keys()`.
- Фактический прогон: `--check` exit 0; `guarded_without_catalog=0`;
  `catalog_without_guard=2` (`edit_humor_library`, `edit_persona` — действия без
  отдельного route-декоратора, классифицируются матрицей); 140 routes,
  74 authenticated-only в `unmatched` (честно перечислены).
- Артефакт: `evidence/m4c/c3/inventory.json` (`generated_from_sha=d4b9b190e`).
- Тест: `tests/test_acl_legacy_inventory.py` (3 PASS); runtime не импортирует
  `tools/*` (F8).
- Явно: авто-миграции/удаления legacy нет; backend endpoints не переименовывались.
