# UR-F вЂ” Р·Р°РєСЂС‹С‚РёРµ С‡РµС‚С‹СЂС‘С… PENDING-СЃС‚СЂРѕРє (UR-RES-07, UR-22, UR-21, UR-29)

- Р‘Р°Р·Р°: production base `b01138b556572e55802755960cf4437eb3ff3b06` (2.58.248).
- Р’РµС‚РєР°: `feat/ur-f-params`; worktree вЂ” `WorkspaceData/worktrees/вЂ¦/ur-f-params-вЂ¦`
  (registered, unit `UR-F`, epic `ur-f-params`).
- РЎСЂРµР·: `plans/features/unified-reply/slice-graph.json` в†’ `UR-F`
  (write scope: `web/app.js`, `web/index.html`, `services/param_catalog.py`,
  `tests/js/*`, `tests/test_ur_ui_effective_config.py`).
- Р”Р°С‚Р°: 26.11.2026. Session: `ses_dec6afb12ffeEPyBweIB86AjMp`.

## РСЃС…РѕРґРЅРѕРµ СЃРѕСЃС‚РѕСЏРЅРёРµ СЃС‚СЂРѕРє РЅР° Р±Р°Р·Рµ (РґРѕ РїСЂР°РІРѕРє)

| РЎС‚СЂРѕРєР° | РЎРѕСЃС‚РѕСЏРЅРёРµ РЅР° `b01138b55` | Р¤Р°РєС‚РёС‡РµСЃРєР°СЏ РїСЂРёС‡РёРЅР° PENDING |
|---|---|---|
| UR-21 | РљР°СЂРєР°СЃ РµСЃС‚СЊ: `eff`-РјРµС‚Р°, Р±РµР№РґР¶Рё no-op/legacy, РіСЂСѓРїРїС‹. РќРѕ `limits.chat_context_fill_ratio` (no-op, РЅРµ С‚СЂРёРіРіРµСЂ СЃ UR-12) Рё `limits.chat_current_question_max_chars` (СЃРёРјРІРѕР»СЊРЅС‹Р№ РїРѕС‚РѕР»РѕРє СЃРЅСЏС‚ SXR-C2-01) РѕСЃС‚Р°РІР°Р»РёСЃСЊ **СЂРµРґР°РєС‚РёСЂСѓРµРјС‹РјРё** РІ В«РћС‚РІРµС‚Р°С… РІ С‡Р°С‚РµВ». РџР»СЋСЃ РєР»РёРµРЅС‚ СЃР°Рј СЂРµС€Р°Р» РїСЂРёРјРµРЅРёРјРѕСЃС‚СЊ СЃРїРёСЃРєРѕРј РєР»СЋС‡РµР№ `UI21_ITEM_UI {hidden/readonly}`. | РќРµ РІС‹РїРѕР»РЅРµРЅРѕ В«РЅРµ С‡РёС‚Р°РµРјРѕРµ СЂР°РЅС‚Р°Р№РјРѕРј СЃРєСЂС‹С‚Рѕ РёР· РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРіРѕ СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёСЏВ»; РєР»РёРµРЅС‚ РґСѓР±Р»РёСЂРѕРІР°Р» РїРѕР»РёС‚РёРєСѓ backend. |
| UR-22 | `/api/config` РѕС‚РґР°С‘С‚ `effective_value/source/eff`; `source` СЂР°Р·Р»РёС‡Р°РµС‚ PG-СЃС‚СЂРѕРєСѓ Рё РґРµС„РѕР»С‚. РќРѕ `readonly` РґР»СЏ legacy/no-op Рё СЃРєСЂС‹С‚РёРµ РїРѕР»СЏ Р·Р°РґР°РІР°Р»РёСЃСЊ **С„СЂРѕРЅС‚РѕРІС‹Рј СЃРїРёСЃРєРѕРј РєР»СЋС‡РµР№**, Р° СЃС‚СЂРѕРєР° СЂРµР¶РёРјР° В«РРЅРёС†РёР°С‚РёРІР°В» Р±СЂР°Р»Р° KV-С„Р»Р°Рі, РёРіРЅРѕСЂРёСЂСѓСЏ env-РѕСЃСЊ backend-РіРµР№С‚Р° (`MCA_INTENTS_ENABLED`). | Frontend СѓРіР°РґС‹РІР°Р» РїСЂРёРјРµРЅРёРјРѕСЃС‚СЊ РІ РґРІСѓС… РјРµСЃС‚Р°С…. |
| UR-29 | РћРґРЅРѕ IANA-РїРѕР»Рµ, РїРѕРёСЃРє, СЃРµСЂРІРµСЂРЅС‹Рµ С‡Р°СЃС‹, offset/DST, РЅР°СЃР»РµРґРѕРІР°РЅРёРµ, Save/Reset РЅР° `mod_time`; `CHAT_TIMEZONE/SUMMARY_TIMEZONE/GOODMORNING_TZ` СЃРєСЂС‹С‚С‹. | Р РµР°Р»РёР·Р°С†РёСЏ СѓР¶Рµ Р±С‹Р»Р°; РЅРµ С…РІР°С‚Р°Р»Рѕ РґРѕРєР°Р·Р°С‚РµР»СЊСЃС‚РІР° РµРґРёРЅСЃС‚РІРµРЅРЅРѕСЃС‚Рё РїРѕРІРµСЂС…РЅРѕСЃС‚Рё РЅР° С‚РµРєСѓС‰РµР№ Р±Р°Р·Рµ. |
| UR-RES-07 | Р Р°Р·РґРµР» В«РћС‚РІРµС‚С‹ РІ С‡Р°С‚РµВ» = `mod_direct` (overview/inspector/settings); СЂРµР¶РёРјС‹ вЂ” РёР· effective-config, РёРЅСЃРїРµРєС‚РѕСЂ РѕС‚РґР°С‘С‚ Р±Р»РѕРєРё СЃРѕР±СЂР°РЅРЅРѕРіРѕ РєРѕРЅС‚РµРєСЃС‚Р°. | РќРµ С…РІР°С‚Р°Р»Рѕ РґРѕРєР°Р·Р°С‚РµР»СЊСЃС‚РІР° В«РґРµР№СЃС‚РІСѓСЋС‰РёР№ СЂРµР¶РёРјВ» РЅР° Р±Р°Р·Рµ (РёРЅРёС†РёР°С‚РёРІР° РїРѕРєР°Р·С‹РІР°Р»Р° KV-С„Р»Р°Рі) + СЃРѕРґРµСЂР¶РёРјРѕРіРѕ РїРѕСЃР»РµРґРЅРµРіРѕ РєРѕРЅС‚РµРєСЃС‚Р° РІ API-С‚РµСЃС‚Рµ. |

RED РЅР° Р±Р°Р·Рµ (РєР°РЅРґРёРґР°С‚СЃРєРёРµ С‚РµСЃС‚С‹ РїСЂРѕС‚РёРІ РєРѕРґР° `b01138b55`; РѕРґРЅРѕСЂР°Р·РѕРІС‹Р№
СЃРЅР°РїС€РѕС‚ Р±Р°Р·С‹ РІ `WorkspaceData/runs/вЂ¦/probe-вЂ¦/base`, СѓРґР°Р»С‘РЅ РїРѕСЃР»Рµ РїСЂРѕРіРѕРЅР°):

```
tests/test_ur_ui_effective_config.py вЂ” 9 failed, 27 passed
  FAILED test_dead_keys_hidden_but_registry_readable
  FAILED test_dead_keys_not_promised_working
  FAILED test_renamed_rows_honest
  FAILED test_effective_meta_honest (РЅРµС‚ РѕСЃРё readonly)
  FAILED test_dead_keys_absent_from_config_and_params_meta
  FAILED test_visible_fields_have_effective_meta (РЅРµС‚ РѕСЃРё readonly)
  FAILED test_readonly_axis_is_backend_contract
  FAILED test_noop_hidden_legacy_marked
         AssertionError: no-op РѕСЃС‚Р°С‘С‚СЃСЏ СЂРµРґР°РєС‚РёСЂСѓРµРјС‹Рј: limits.chat_context_fill_ratio
  FAILED test_every_visible_field_carries_eff (eff Р±РµР· readonly)
tests/js/unified_ui21_test.js вЂ” AssertionError: UR-22: readonly вЂ” РёР· item.eff.readonly
tests/js/ur_ui_settings_test.js вЂ” AssertionError: UR-22: Р±РµР№РґР¶ СЂРµР¶РёРјР° Р±РµСЂС‘С‚ СЃС‚Р°С‚СѓСЃ
                                  РёР· backend-РіРµР№С‚Р°
```

Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅРѕ РЅР° Р±Р°Р·Рµ `tests/js/ur_ui_settings_test.js` РїР°РґР°Р» РЅР° СѓСЃС‚Р°СЂРµРІС€РµРј
СЃС‚Р°С‚РёС‡РµСЃРєРѕРј `MODULES` (РїРѕСЃР»Рµ MOD-ACL-UX-01 РєР°СЂС‚РѕС‡РєРё РїСЂРёС…РѕРґСЏС‚ РёР· DTO) Рё РЅР°
Р·Р°РІРёСЃРёРјРѕСЃС‚Рё С‡Р°СЃРѕРІ РѕС‚ РєР°Р»РµРЅРґР°СЂРЅРѕР№ РґР°С‚С‹ РїСЂРѕРіРѕРЅР°; РѕР±Р° РјРµСЃС‚Р° РїСЂРёРІРµРґРµРЅС‹ Рє
РґРµС‚РµСЂРјРёРЅРёСЂРѕРІР°РЅРЅРѕРјСѓ РєРѕРЅС‚СЂР°РєС‚Сѓ (DTO-РёРЅСЉРµРєС†РёСЏ, `fetchedAt = now`).

## Р§С‚Рѕ РёР·РјРµРЅРµРЅРѕ

### 1. Backend вЂ” РµРґРёРЅСЃС‚РІРµРЅРЅС‹Р№ РёСЃС‚РѕС‡РЅРёРє РїСЂРёРјРµРЅРёРјРѕСЃС‚Рё (`services/param_catalog.py`)

- Р’ `_UR_F_WITHOUT_RUNTIME_READER` РґРѕР±Р°РІР»РµРЅС‹:
  - `CHAT_CONTEXT_FILL_RATIO` вЂ” РїРѕР»Рµ В«Р·Р°РїРѕР»РЅРµРЅРёРµ РѕРєРЅР°В» СѓР±СЂР°РЅРѕ (UR-21,
    РЅРµ С‚СЂРёРіРіРµСЂ РєРѕРЅСЃРїРµРєС‚Р° СЃ UR-12; Р·РЅР°С‡РµРЅРёРµ РѕСЃС‚Р°С‘С‚СЃСЏ С‡РёС‚Р°РµРјС‹Рј РїРѕ PG-РєР»СЋС‡Сѓ);
  - `CHAT_CURRENT_QUESTION_MAX_CHARS` вЂ” Р»РёРјРёС‚ РІРѕРїСЂРѕСЃР° СѓР±СЂР°РЅ (UR-21.01;
    СЃРёРјРІРѕР»СЊРЅС‹Р№ РїРѕС‚РѕР»РѕРє СЃРЅСЏС‚ SXR-C2-01, РїРѕР»РЅС‹Р№ С‚РµРєСЃС‚ РґРѕС…РѕРґРёС‚ РґРѕ L1/Writer).
- РџРѕРґРїРёСЃРё РѕР±РѕРёС… РєР»СЋС‡РµР№ Р±РѕР»СЊС€Рµ РЅРµ РѕР±РµС‰Р°СЋС‚ РїРѕРІРµРґРµРЅРёСЏ: В«РЅРµ РґРµР№СЃС‚РІСѓРµС‚ / РЅРµ
  С‡РёС‚Р°РµС‚ / РІС‹РІРµРґРµРЅ РёР· РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРіРѕ СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёСЏВ».
- `effective_meta("limits.chat_current_question_max_chars")` СЃРѕС…СЂР°РЅСЏРµС‚
  `no_op` + С‡РµСЃС‚РЅСѓСЋ РїСЂРёС‡РёРЅСѓ (Р·РЅР°С‡РµРЅРёРµ С‡РёС‚Р°РµРјРѕ РґР»СЏ РґРёР°РіРЅРѕСЃС‚РёРєРё).
- РќРѕРІР°СЏ РѕСЃСЊ РєРѕРЅС‚СЂР°РєС‚Р° `eff.readonly`: С‚Рµ Р¶Рµ РєР»СЋС‡Рё, С‡С‚Рѕ СЂР°РЅСЊС€Рµ С„СЂРѕРЅС‚РѕРІС‹Р№
  `UI21_ITEM_UI` РїРѕРјРµС‡Р°Р» readonly (compat-РєР°РїС‹/РґРѕР»Рё + РґРІР° СЃРЅСЏС‚С‹С… РїРѕР»СЏ),
  РѕР±СЉСЏРІР»РµРЅС‹ РІ `_EFFECTIVE_READONLY`; РЅРѕРІС‹С… Р·Р°РїСЂРµС‚РѕРІ РЅРµС‚ вЂ” РїРѕР»РёС‚РёРєР°
  РїРµСЂРµРЅРµСЃРµРЅР° РЅР° backend. РћСЃСЊ С‚РѕС‡РµС‡РЅР°СЏ: РЅР°РїСЂРёРјРµСЂ
  `limits.chat_running_summary_tail` (legacy, РЅРѕ С‡РёС‚Р°РµС‚СЃСЏ fallback) РѕСЃС‚Р°С‘С‚СЃСЏ
  СЂРµРґР°РєС‚РёСЂСѓРµРјС‹Рј вЂ” РѕРіСѓР»СЊРЅРѕРіРѕ РїСЂР°РІРёР»Р° В«legacy = readonlyВ» РЅРµС‚.

РС‚РѕРі: РЅРё РѕРґРЅРѕРіРѕ СЂРµРґР°РєС‚РёСЂСѓРµРјРѕРіРѕ `no_op` РІ РіСЂСѓРїРїР°С… В«РћС‚РІРµС‚РѕРІ РІ С‡Р°С‚РµВ»;
`legacy`-РїРѕР»СЏ РѕСЃС‚Р°СЋС‚СЃСЏ РІРёРґРёРјС‹РјРё Рё РїРѕРјРµС‡РµРЅРЅС‹РјРё (`eff.status=legacy`).

### 2. Frontend РЅРµ СѓРіР°РґС‹РІР°РµС‚ (`web/app.js`, `web/index.html`)

- `UI21_ITEM_UI` Р±РѕР»СЊС€Рµ РЅРµ СЃРѕРґРµСЂР¶РёС‚ `hidden`/`readonly`: РѕСЃС‚Р°Р»РёСЃСЊ С‚РѕР»СЊРєРѕ
  РїСЂРµР·РµРЅС‚Р°С†РёРѕРЅРЅС‹Рµ `advanced`. `__uiReadonly` РІС‹РІРѕРґРёС‚СЃСЏ РёР·
  `item.eff.readonly` (backend-РєРѕРЅС‚СЂР°РєС‚); СЃРєСЂС‹С‚РёРµ РІС‹РїРѕР»РЅСЏРµС‚ backend.
- `directModesView()` РґР»СЏ В«РРЅРёС†РёР°С‚РёРІС‹В» РёСЃРїРѕР»СЊР·СѓРµС‚ backend-РіРµР№С‚ РјРѕРґСѓР»СЏ:
  `moduleModeStatus()` Р±РµСЂС‘С‚ `state.desired/effective_runtime/source` Рё
  `gate.effective/source`; env-Р±Р»РѕРєРёСЂРѕРІРєР° РїРѕРєР°Р·С‹РІР°РµС‚СЃСЏ РєР°Рє
  В«РІРєР»СЋС‡РµРЅРѕ, РЅРѕ Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅРѕ: Р°РІР°СЂРёР№РЅС‹Р№ РїРµСЂРµРєР»СЋС‡Р°С‚РµР»СЊ СЃРµСЂРІРµСЂР°В», Р±РµР№РґР¶ вЂ”
  В«Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅРѕВ». РЎС‚Р°СЂС‹Р№ payload Р±РµР· DTO вЂ” РїСЂРµР¶РЅСЏСЏ СЃРµРјР°РЅС‚РёРєР° `item`.
- РќРёРєР°РєРёС… РЅРѕРІС‹С… РєР»Р°СЃСЃРёС„РёРєР°С‚РѕСЂРѕРІ, СЌРЅРґРїРѕРёРЅС‚РѕРІ, Р»РёРјРёС‚РѕРІ Рё Р¶С‘СЃС‚РєРѕ
  Р·Р°С…Р°СЂРґРєРѕР¶РµРЅРЅС‹С… СЃРїРёСЃРєРѕРІ РєР»СЋС‡РµР№ РЅРµ РґРѕР±Р°РІР»РµРЅРѕ.

### 3. РўРµСЃС‚С‹

- `tests/test_ur_ui_effective_config.py` (36 passed):
  - `TestDirectGroupApplicability` вЂ” РІСЃРµ РїРѕР»СЏ РіСЂСѓРїРї mod_direct РЅРµСЃСѓС‚
    `status/active_consumer/units/reason_inactive/readonly`; no-op СЃРєСЂС‹С‚С‹,
    legacy РїРѕРјРµС‡РµРЅС‹; РѕСЃСЊ `readonly` вЂ” С‚РѕС‡РµС‡РЅР°СЏ Рё backend-РЅР°СЏ; СЃРЅСЏС‚С‹Рµ РїРѕР»СЏ
    РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‚ РІ `/api/config`;
  - `TestEffectiveConfigSource` вЂ” РѕРґРёРЅР°РєРѕРІРѕРµ Р·РЅР°С‡РµРЅРёРµ (8000) РІ СЏРІРЅРѕР№
    global-СЃС‚СЂРѕРєРµ Рё СЃРёРЅС‚РµС‚РёС‡РµСЃРєРѕРј РґРµС„РѕР»С‚Рµ СЂР°Р·Р»РёС‡Р°РµС‚СЃСЏ РўРћР›Р¬РљРћ РёСЃС‚РѕС‡РЅРёРєРѕРј
    (`global` vs `default`) вЂ” UI РЅРµ РјРѕР¶РµС‚ РІС‹РІРµСЃС‚Рё СЌС‚Рѕ РёР· KV;
  - `TestTimeSingleSurface` вЂ” СЂРѕРІРЅРѕ РѕРґРёРЅ `data-time-zone-input` РІ СЂР°Р·РјРµС‚РєРµ,
    legacy-РїРѕСЏСЃР° СЃРєСЂС‹С‚С‹, `/api/config/time` РЅРµСЃС‘С‚
    `iana/source/now_local/as_of_utc/utc_offset/weekday/is_dst/configured`;
  - `TestTurnDiagnostics.test_last_assembled_context_content` вЂ” Р±Р»РѕРєРё
    РїРѕСЃР»РµРґРЅРµРіРѕ СЃРѕР±СЂР°РЅРЅРѕРіРѕ РєРѕРЅС‚РµРєСЃС‚Р° (kind/РґР°С‚С‹/source IDs/РїСЂРёС‡РёРЅР° РїСЂРѕРїСѓСЃРєР°)
    Рё РїРѕС‚РµСЂРё РїСЂРёС…РѕРґСЏС‚ РёР· СЃСѓС‰РµСЃС‚РІСѓСЋС‰РµР№ С‚СЂР°СЃСЃС‹ `direct_turn_selection`.
- `tests/js/unified_ui21_test.js` вЂ” readonly РёР· `item.eff.readonly`, РєР»РёРµРЅС‚
  РЅРµ СЃРєСЂС‹РІР°РµС‚ РєР»СЋС‡Рё СЃР°Рј (UR-22).
- `tests/js/ur_ui_settings_test.js` вЂ” РєР°СЂС‚РѕС‡РєР° В«Р’СЂРµРјСЏВ» РёР· DTO, РґРµС‚РµСЂРјРёРЅРёСЂРѕРІР°РЅРЅС‹Рµ
  С‡Р°СЃС‹, РіРµР№С‚ РёРЅРёС†РёР°С‚РёРІС‹ (blocked/active), РёСЃС‚РѕС‡РЅРёРє РґРµР№СЃС‚РІСѓСЋС‰РµРіРѕ СЂРµР¶РёРјР°.
- `tests/test_cfg03_param_audit.py` вЂ” С‚РѕС‡РЅС‹Р№ РїРёРЅ СЃРєСЂС‹С‚С‹С… РєР»СЋС‡РµР№ РѕР±РЅРѕРІР»С‘РЅ РЅР°
  РґРІР° РЅРѕРІС‹С… (РґРѕРєСѓРјРµРЅС‚РёСЂРѕРІР°РЅРЅС‹Р№ СЃРїРёСЃРѕРє, РЅРµ РѕСЃР»Р°Р±Р»РµРЅРёРµ).
- `tools/ui_urf_visual_e2e.py` вЂ” РІРёР·СѓР°Р»СЊРЅР°СЏ РїСЂРёС‘РјРєР°: РґРІР° СЃРЅСЏС‚С‹С… РїРѕР»СЏ РІ
  `deadTitles`, РѕРґРЅРѕ IANA-РїРѕР»Рµ Рё РѕС‚СЃСѓС‚СЃС‚РІРёРµ РІС‚РѕСЂС‹С… РїРѕСЏСЃРѕРІ РЅР° СЌРєСЂР°РЅРµ В«Р’СЂРµРјСЏВ»,
  Р±РµР№РґР¶/СЃС‚СЂРѕРєР° В«РРЅРёС†РёР°С‚РёРІС‹В» РёР· backend-РіРµР№С‚Р°.
- `tests/js/ur_ui_settings_test.js` вЂ” СѓР±СЂР°РЅР° Р·Р°РІРёСЃРёРјРѕСЃС‚СЊ РѕС‚ РєР°Р»РµРЅРґР°СЂРЅРѕР№ РґР°С‚С‹
  (`timeStateFetchedAt = Date.now()`) Рё РѕС‚ СЃС‚Р°С‚РёС‡РµСЃРєРѕРіРѕ `MODULES`; С‚РµСЃС‚
  РїРѕ-РїСЂРµР¶РЅРµРјСѓ РїСЂРѕРІРµСЂСЏРµС‚ СЃРµСЂРІРµСЂРЅСѓСЋ Р°СЂРёС„РјРµС‚РёРєСѓ С‡Р°СЃРѕРІ Рё DTO-СЂРµРµСЃС‚СЂ.

## РџСЂРѕРІРµСЂРєРё (РєР°РЅРґРёРґР°С‚)

| РџСЂРѕРІРµСЂРєР° | РљРѕРјР°РЅРґР° | Р РµР·СѓР»СЊС‚Р°С‚ |
|---|---|---|
| Python, СЃС‚СЂРѕРєРё UR-F | `pytest tests/test_ur_ui_effective_config.py -q` | 36 passed |
| Python, РєР°С‚Р°Р»РѕРі/Р°СѓРґРёС‚/СЃСЂРµР·С‹ | `pytest tests/test_param_catalog.py tests/test_cfg03_param_audit.py tests/test_ur_11_single_owner.py tests/test_ur_12_summary_watermark.py tests/test_ur_context_selection.py tests/test_ur_c_clock.py tests/test_ur_ui_effective_config.py -q` | 201 passed, 1 pre-existing failed (`test_visible_dead_knobs_are_exactly_documented`: 4 РЅРµСЃРІСЏР·Р°РЅРЅС‹С… РєР»СЋС‡Р° graph/dig Р±С‹Р»Рё РІРЅРµ СЃРїРёСЃРєР° Рё РґРѕ РїСЂР°РІРѕРє) |
| Python, РёРЅСЃРїРµРєС‚РѕСЂ/СЃСЂРµР·С‹ | `pytest tests/test_webapp_api.py tests/test_ur_f_inspector_step1.py вЂ¦ test_ur_e_speech.py -q` | 361 passed, 1 pre-existing failed (`test_ur_f_inspector_step1::test_identical_quotes_credit_only_the_surviving_item`, `FakeDB` вЂ” РїР°РґР°РµС‚ Рё РЅР° Р±Р°Р·Рµ) |
| JS, СЃС‚СЂРѕРєРё | `node tests/js/ur_ui_settings_test.js`, `node tests/js/unified_ui21_test.js` | `UR-F-UI-OK`, `UNIFIED-UI21-OK` |
| JS, РІРµСЃСЊ РєР°С‚Р°Р»РѕРі | `node tests/js/*_test.js` (149 С„Р°Р№Р»РѕРІ) | 7 failed вЂ” РІСЃРµ 7 РёРґРµРЅС‚РёС‡РЅРѕ РїР°РґР°СЋС‚ РЅР° Р±Р°Р·Рµ `b01138b55` (`_cogBlitLabel`, `_embedModelSwapGuard`, oversight/menu-РїРёРЅС‹) |
| Р’РёР·СѓР°Р» (Playwright) | `python tools/ui_urf_visual_e2e.py --out вЂ¦/visual` | `URF-VISUAL-OK`; desktop 1440 + mobile 390; console errors = 0; `zoneInputCount=1`, `legacyTzFields=0`, `initiativeBadge=Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅРѕ` |
| РЎРёРЅС‚Р°РєСЃРёСЃ | `py_compile` (3 С„Р°Р№Р»Р°), `node --check web/app.js` | OK |

РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ: effective-config С‡РёС‚Р°РµС‚СЃСЏ РёР· `services/param_catalog.py`
(Р·Р°РІРѕРґСЃРєРёРµ РґРµС„РѕР»С‚С‹) Рё `bot_settings` (PG-СЃС‚СЂРѕРєРё); per-chat override вЂ” РёР·
`chat_profiles`. Р’РёР·СѓР°Р»СЊРЅС‹Р№ РїСЂРѕРіРѕРЅ РёСЃРїРѕР»СЊР·СѓРµС‚ СЂРµР°Р»СЊРЅС‹Рµ `web/app.js` Рё
`web/index.html` СЃ РґРµС‚РµСЂРјРёРЅРёСЂРѕРІР°РЅРЅС‹РјРё API-СЃС‚Р°Р±Р°РјРё (СЂРµР°Р»СЊРЅР°СЏ РѕС‚РїСЂР°РІРєР° РІ
Telegram РЅРµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ). РЎРµРєСЂРµС‚С‹ РЅРµ С‡РёС‚Р°Р»РёСЃСЊ Рё РЅРµ Р»РѕРіРёСЂРѕРІР°Р»РёСЃСЊ.

## РЎРѕСЃС‚РѕСЏРЅРёРµ СЃС‚СЂРѕРє (РґР»СЏ Р±РёРЅРґРёРЅРіР°)

| РЎС‚СЂРѕРєР° | Р РµР·СѓР»СЊС‚Р°С‚ | Р”РѕРєР°Р·Р°С‚РµР»СЊСЃС‚РІРѕ |
|---|---|---|
| **UR-21** | implemented (РґРІР° СЃРЅСЏС‚С‹С… РїРѕР»СЏ СѓР±СЂР°РЅС‹ РёР· СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёСЏ; РєР»РёРµРЅС‚ РЅРµ РґСѓР±Р»РёСЂСѓРµС‚ РїРѕР»РёС‚РёРєСѓ; РІСЃРµ РїРѕР»СЏ РіСЂСѓРїРїС‹ РЅРµСЃСѓС‚ РјРµС‚Сѓ, no-op СЃРєСЂС‹С‚С‹, legacy РїРѕРјРµС‡РµРЅС‹) | `tests/test_ur_ui_effective_config.py::TestDirectGroupApplicability` (5 С‚РµСЃС‚РѕРІ), `TestCatalogHonesty`; `tests/js/unified_ui21_test.js`; Playwright `direct-settings/direct-limits` вЂ” `deadFound=[]`, hScroll=false |
| **UR-22** | implemented (readonly РёР· `eff.readonly`; СЂРµР¶РёРј РёРЅРёС†РёР°С‚РёРІС‹ РёР· backend-РіРµР№С‚Р°; `source` СЂР°Р·Р»РёС‡Р°РµС‚ СЃС‚СЂРѕРєСѓ PG Рё РґРµС„РѕР»С‚ РїСЂРё РѕРґРёРЅР°РєРѕРІРѕРј Р·РЅР°С‡РµРЅРёРё) | `TestEffectiveConfigSource`, `TestDirectGroupApplicability::test_readonly_axis_is_backend_contract`, `test_every_visible_field_carries_eff`; `tests/js/ur_ui_settings_test.js` Рї.6; Playwright `modes-*` (Р±РµР№РґР¶ В«Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅРѕВ») |
| **UR-29** | already satisfied with proof (РѕРґРЅРѕ editable IANA-РїРѕР»Рµ СЃ РїРѕРёСЃРєРѕРј, СЃРµСЂРІРµСЂРЅС‹Рµ С‡Р°СЃС‹, offset/DST, РЅР°СЃР»РµРґРѕРІР°РЅРёРµ, Save/Reset; РІС‚РѕСЂС‹С… С‡Р°СЃРѕРІС‹С… РїРѕСЏСЃРѕРІ РЅРµС‚) | `TestTimeSingleSurface` (4 С‚РµСЃС‚Р°), `TestTimeSurface`; Playwright `time-desktop-1440`/`time-mobile-390`: `zoneInputCount=1`, `legacyTzFields=0`, С‡Р°СЃС‹ С‚РёРєР°СЋС‚ РѕС‚ СЃРµСЂРІРµСЂРЅРѕР№ Р±Р°Р·С‹ |
| **UR-RES-07** | already satisfied with proof + honest mode fix (РґРµР№СЃС‚РІСѓСЋС‰РёР№ СЂРµР¶РёРј/РёСЃС‚РѕС‡РЅРёРє; СЃРѕРґРµСЂР¶РёРјРѕРµ РїРѕСЃР»РµРґРЅРµРіРѕ РєРѕРЅС‚РµРєСЃС‚Р° РІ РёРЅСЃРїРµРєС‚РѕСЂРµ; РґРµРєРѕСЂР°С‚РёРІРЅС‹С… no-op-РїРѕР»РµР№ РЅРµС‚) | `TestTurnDiagnostics::test_last_assembled_context_content` + СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёРµ `test_chain_view_maps_all_stages`; `tests/js/ur_ui_settings_test.js` Рї.3вЂ“5; Playwright `modes-*`, `inspector-*`; `deadFound=[]` |

## РћСЃС‚Р°С‚РѕС‡РЅРѕРµ / С‡РµСЃС‚РЅС‹Рµ РѕРіСЂР°РЅРёС‡РµРЅРёСЏ

- `tests/test_cfg03_param_audit.py::test_visible_dead_knobs_are_exactly_documented`
  Рё `tests/test_ur_f_inspector_step1.py::test_identical_quotes_credit_only_the_surviving_item`
  РїР°РґР°СЋС‚ РЅР° Р±Р°Р·Рµ `b01138b55` Рё РїРѕСЃР»Рµ РїСЂР°РІРѕРє; Рє СЃС‚СЂРѕРєР°Рј СЌС‚РѕРіРѕ СЃСЂРµР·Р° РЅРµ
  РѕС‚РЅРѕСЃСЏС‚СЃСЏ, РЅРµ РёСЃРїСЂР°РІР»СЏР»РёСЃСЊ (РЅРµ СЂР°СЃС€РёСЂСЏР» scope).
- 7 РїР°РґРµРЅРёР№ JS-РєР°С‚Р°Р»РѕРіР° вЂ” Р±Р°Р·РѕРІС‹Рµ (РїСЂРѕРІРµСЂРµРЅРѕ РїСЂРѕРіРѕРЅРѕРј С‚РµС… Р¶Рµ С‚РµСЃС‚РѕРІ РЅР°
  СЃРЅР°РїС€РѕС‚Рµ `b01138b55`), Рє UR-F РЅРµ РѕС‚РЅРѕСЃСЏС‚СЃСЏ.
- Browser Use РІ СЌС‚РѕРј РїСЂРѕРіРѕРЅРµ РЅРµ РёСЃРїРѕР»СЊР·РѕРІР°Р»СЃСЏ: Playwright РїРѕРєСЂС‹Р» desktop
  1440 Рё mobile 390 РЅР° СЂРµР°Р»СЊРЅС‹С… `web/app.js`/`web/index.html` СЃ С‡РёСЃС‚РѕР№
  РєРѕРЅСЃРѕР»СЊСЋ; РІРёР·СѓР°Р»СЊРЅС‹Р№ РєРѕРЅС‚СЂР°РєС‚ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёС… СЌРєСЂР°РЅРѕРІ РЅРµ РјРµРЅСЏР»СЃСЏ, РєСЂРѕРјРµ
  С‡РµСЃС‚РЅРѕРіРѕ Р±РµР№РґР¶Р° РёРЅРёС†РёР°С‚РёРІС‹ Рё РёСЃС‡РµР·РЅРѕРІРµРЅРёСЏ РґРІСѓС… РјС‘СЂС‚РІС‹С… РїРѕР»РµР№.
- `WORKER_BUDGET_TZ` РѕСЃС‚Р°С‘С‚СЃСЏ РѕС‚РґРµР»СЊРЅРѕР№ РЅР°СЃС‚СЂРѕР№РєРѕР№ С„РѕРЅРѕРІРѕРіРѕ РґРЅСЏ Р±СЋРґР¶РµС‚РѕРІ
  (С‡РёС‚Р°РµС‚СЃСЏ `worker_budget`/`dream_worker`); СЌС‚Рѕ РЅРµ РІС‚РѕСЂРѕР№ С‡Р°СЃРѕРІРѕР№ РїРѕСЏСЃ
  С‡Р°С‚Р°: chat-РїСѓС‚СЊ Р±СЋРґР¶РµС‚Р° РёРґС‘С‚ С‡РµСЂРµР· `ChatClock`
  (`resolve_chat_timezone_sync`).
- `feature_gate`/`last_applied_turn` РІ `/api/config` РїРѕ-РїСЂРµР¶РЅРµРјСѓ РЅРµ
  РѕС‚РґР°СЋС‚СЃСЏ (РїСЂРёРЅСЏС‚С‹Р№ honest gap UR-22.1); РґР»СЏ СЂРµР¶РёРјР° РёРЅРёС†РёР°С‚РёРІС‹ РёСЃРїРѕР»СЊР·РѕРІР°РЅ
  СѓР¶Рµ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёР№ `modules[].gate`/`state`, Р±РµР· РЅРѕРІРѕРіРѕ СЌРЅРґРїРѕРёРЅС‚Р°.
