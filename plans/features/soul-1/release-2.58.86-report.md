# RELEASE-SOUL1-25886 вЂ” РёР·РѕР»РёСЂРѕРІР°РЅРЅС‹Р№ СЂРµР»РёР· SOUL-1 (2.58.86): РѕС‚С‡С‘С‚

- **Р›РµР№РЅ:** REL-SOUL (release engineer). Р РµР¶РёРј: release-РІРµС‚РєР° + С€С‚Р°С‚РЅС‹Р№ РґРµРїР»РѕР№.
- **Р’С…РѕРґ:** `soul-release-prep.md` (В§3 СЃРїРѕСЃРѕР± (b), В§4 РёСЃРїРѕР»РЅРёРјР°СЏ РїСЂРѕС†РµРґСѓСЂР° РІРєР»СЋС‡РµРЅРёСЏ,
  В§5 precondition), `review-payload-verify.md` R2 (F1/F3 Р·Р°РєСЂС‹С‚С‹; РѕСЃС‚Р°С‚РѕРє вЂ” СЂРµР»РёР·РЅС‹Р№
  РїСЂРѕРіРѕРЅ: (ii), F5, F2/F4), `review-soul-prep.md` R3, РґРёСЂРµРєС‚РёРІР° РІР»Р°РґРµР»СЊС†Р°
  `source-release-correction-2026-10-18.md`, `evidence/soul-release/postfix/**`.
- **РџСЂРѕРґ РґРѕ СЂРµР»РёР·Р°:** `9552686391dfe69dd7cb08ba7cd800a8a6c5106e` (`release/win-glass-2.58.85`,
  APP_VERSION 2.58.85). Rollback-С†РµР»СЊ вЂ” СЌС‚Р° Р¶Рµ РІРµС‚РєР°.
- **PET_PROJECT:** РІСЃРµ РіРѕС‚РѕРІС‹Рµ РѕСЃРё РІРєР»СЋС‡Р°СЋС‚СЃСЏ СЃСЂР°Р·Сѓ РІРѕ РІСЃРµС… РїРѕРґРєР»СЋС‡С‘РЅРЅС‹С… С‡Р°С‚Р°С…; РґРµРїР»РѕР№
  В«РІСЃС‘ OFFВ» вЂ” РёР·РѕР»СЏС†РёСЏ СЂРµР»РёР·Р° (РЅРµ РєР°РЅР°СЂРµР№РєР°); rollback-РјРµС…Р°РЅРёР·РјС‹ СЃРѕС…СЂР°РЅРµРЅС‹.

## 1. Р’РµС‚РєР° Рё СЃРѕСЃС‚Р°РІ

| РџРѕР»Рµ | Р—РЅР°С‡РµРЅРёРµ |
|---|---|
| DEPLOY_SOURCE | Р»РѕРєР°Р»СЊРЅС‹Р№ СЂРµРїРѕ `C:\Code\Python\adminbot`, worktree `OPENCODE_WORKFLOW_SCRATCH/soul1-release-25886/wt`, РІРµС‚РєР° `release/soul1-2.58.86` |
| Р‘Р°Р·Р° РІРµС‚РєРё | **`9552686391dfe69dd7cb08ba7cd800a8a6c5106e`** (2.58.85, Р·Р°РґРµРїР»РѕРµРЅРЅС‹Р№ WG-СЂРµР»РёР·) |
| РЎРїРѕСЃРѕР± | (b) tree-port: `git checkout 915aa3c7 -- services web config tests tools plans README.md AGENTS.md` |
| РљРѕРјРјРёС‚С‹ | `432edf80` (tree-port SOUL-1) + `e0756310` (bump 2.58.86, 31 С„Р°Р№Р») + `eafbe2e7` (runbook В§4вЂ“В§5 sync) |
| Р”РµР»СЊС‚Р° vs Р±Р°Р·Р° | **628 С„Р°Р№Р»РѕРІ** (СЃРј. `evidence/release-soul-25886/delta-vs-base.txt`, `isolation-classification.txt`) |
| Runtime-СЌРєРІРёРІР°Р»РµРЅС‚РЅРѕСЃС‚СЊ | `git diff 72b91d6e HEAD -- services` = РџРЈРЎРўРћ; `git diff 0ca661fe master -- web services` = РџРЈРЎРўРћ; `git diff master HEAD -- services web` = РџРЈРЎРўРћ |
| Р‘Р°РјРїР° РІРµСЂСЃРёРё | 2.58.81в†’2.58.86: settings + README + F8-meta (HEAD `432edf80`) + 24 py-РїРёРЅР° + 4 JS-РїРёРЅР° = 31 С„Р°Р№Р» |
| РР·РѕР»СЏС†РёСЏ | 0 РЅРµРєР»Р°СЃСЃРёС„РёС†РёСЂРѕРІР°РЅРЅС‹С…; CFG (`plans/features/cfg/**`) РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚; WG-Р°СЂС‚РµС„Р°РєС‚С‹ Р±Р°Р№С‚-РІ-Р±Р°Р№С‚ РїСЂРѕРґСѓ (`fullscreen-policy.js` `96db06425079`, `glass-refraction.js` `6a09d962d59d`, `glass-probe.js` `b2e6a1f987c6`, 2 JS-С‚РµСЃС‚Р° WG, `tools/ui_win_glass_refraction_e2e.py`); scratch/node_modules РІ РґРµСЂРµРІРѕ РЅРµ РІС…РѕРґСЏС‚ |
| РЎРµРєСЂРµС‚-СЃРєР°РЅ РґРµР»СЊС‚С‹ | 22 В«СЃСЂР°Р±Р°С‚С‹РІР°РЅРёСЏВ» вЂ” РІСЃРµ С‚РµСЃС‚РѕРІС‹Рµ РґСѓР±Р»Рё (`sk-SYNTHETIC-*`, `123456:TEST_TOKEN_*`, R17-РјР°СЂРєРµСЂС‹); СЂРµР°Р»СЊРЅС‹С… СЃРµРєСЂРµС‚РѕРІ РЅРµС‚ |

## 1-bis. РС‚РѕРі РґРµРїР»РѕСЏ

| РџРѕР»Рµ | Р—РЅР°С‡РµРЅРёРµ |
|---|---|
| deployed_commit | **`eafbe2e7b792c74eeb91735e183b767c6b85d73c`** (РІРµС‚РєР° `release/soul1-2.58.86`, prototype; Р°СЂС‚РµС„Р°РєС‚-РєРѕРјРјРёС‚С‹ РёРґСѓС‚ РїРѕСЃР»Рµ Рё runtime РЅРµ РјРµРЅСЏСЋС‚) |
| РџСЂРѕРґ РґРѕ/РїРѕСЃР»Рµ | 2.58.85 (`95526863`) в†’ **2.58.86**, healthz ok (loopback + 443 + РёР·РІРЅРµ) |
| Push | `release/soul1-2.58.86` в†’ origin (`ls-remote` = tip) |
| РњРёРіСЂР°С†РёРё | SQLite v36 `humor_samples` вЂ” Р°РґРґРёС‚РёРІРЅР°СЏ, РїСЂРёРјРµРЅРµРЅР° (backup-guard 153 СЃ) |
| DDL PG | 0 (РєСЂРѕРјРµ С€С‚Р°С‚РЅС‹С… СЃС‚СЂРѕРє `flags.*`/`character.core`) |
| Rollback-С†РµР»СЊ | `release/win-glass-2.58.85` (`95526863`) вЂ” Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРёР№ РѕС‚РєР°С‚ РїРµСЂРІРѕРіРѕ РїСЂРѕРіРѕРЅР° РѕС‚СЂР°Р±РѕС‚Р°Р» Рё РїРѕРґС‚РІРµСЂР¶РґС‘РЅ |
| SSH-РґРёСЃС†РёРїР»РёРЅР° | 1 recon + 1 РѕСЃРЅРѕРІРЅРѕР№ РїСЂРѕРіРѕРЅ (РїРµСЂРІС‹Р№ РїСЂРѕРіРѕРЅ вЂ” Р°РІС‚Рѕ-РѕС‚РєР°С‚) + РєРѕСЂРѕС‚РєРёРµ read-only РґРёР°РіРЅРѕСЃС‚РёРєРё (РґРёР°РіРЅРѕР· РјРёРіСЂР°С†РёРё/С„РёРЅР°Р»СЊРЅР°СЏ С„РёРєСЃР°С†РёСЏ), РІСЃРµ РѕРґРёРЅРѕС‡РЅС‹Рµ, Р±РµР· СЂРµС‚СЂР°РµРІ; СЃРµРєСЂРµС‚РѕРІ РІ Р»РѕРіР°С… РЅРµС‚ |


| РџСЂРѕРіРѕРЅ | Р РµР·СѓР»СЊС‚Р°С‚ | РђСЂС‚РµС„Р°РєС‚ |
|---|---|---|
| node `tests/js/*.js` (87 С„Р°Р№Р»РѕРІ) | **87 OK / 0 RED** (РѕР¶РёРґР°РЅРёРµ В«84/85 + RED round1025_design_tokensВ» РЅРµ РїРѕРґС‚РІРµСЂРґРёР»РѕСЃСЊ вЂ” master-Р»РёРЅРёСЏ СЃРѕРґРµСЂР¶РёС‚ РёСЃРїСЂР°РІР»РµРЅРЅС‹Р№ С‚РµСЃС‚+app.js) | `preflight-node-guards.txt` |
| `tests/test_soul1_*.py` (30 С„Р°Р№Р»РѕРІ) | **599 passed** | `preflight-soul1-set.txt` |
| parity OFF | **13 passed** | `preflight-parity.txt` |
| `tools/gen_param_registry_round1025.py --check` | **575 == REGISTRY** ok | `preflight-registry-check.txt` |
| РџРµСЂРёРјРµС‚СЂ `-k "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or glass or persona or prompt or registry or catalog"` | **3917 passed / 0 failed** (10244 deselected; +2 Рє РѕР¶РёРґР°РµРјС‹Рј 3915 вЂ” РЅРѕРІС‹Рµ F1/F3-С‚РµСЃС‚С‹ `72b91d6e`) | `preflight-perimeter.txt` |
| Embedding-sweep `-k "embedding or graphrag or quota or summary_memory or memory_maintenance"` | **534 passed / 0** | `preflight-embedding-sweep.txt` |
| РЎРјРµР¶РЅС‹Рµ (prompt_migrations + round1025_f8_registry) | **70 passed** | `preflight-adjacent-tests.txt` |
| FS-РјР°С‚СЂРёС†Р° `tools/ui_asap8_w2_fullscreen_e2e.py` | **12/12 PASS** | `preflight-ui-fs-matrix.txt` |
| W7 dev-API `tools/ui_soul1_w7_fullscreen_explain_e2e.py` | **5/5 PASS, 88 РїСЂРѕРІРµСЂРѕРє** | `preflight-ui-w7-explain.txt` |
| W6 speech e2e `tools/ui_soul1_w6_speech_e2e.py` | **RED СЃ Р·Р°РєРѕРјРјРёС‡РµРЅРЅРѕР№ С„РёРєСЃС‚СѓСЂРѕР№ / 0 failures СЃ РїРµСЂРµ-СЃРЅСЏС‚РѕР№** | `preflight-ui-w6-speech-stale-fixture.txt`, `preflight-ui-w6-speech-regenfixture.txt`, `w6-e2e-diagnosis.txt` |
| W2-SHELL e2e (U01/U02) | **RED вЂ” РїСЂРµРґСЃСѓС‰РµСЃС‚РІСѓРµС‚ РЅР° Р±Р°Р·Рµ** (РёРґРµРЅС‚РёС‡РЅР°СЏ СЃРёРіРЅР°С‚СѓСЂР° РЅР° РґРµСЂРµРІРµ `95526863`) | `preflight-ui-shell-e2e.txt`, `preflight-ui-shell-e2e-on-base95526863.txt`, `w2-shell-e2e-diagnosis.txt` |
| Frozen-check (Р°РґР°РїС‚РµСЂ Рє Р±Р°Р·Рµ; upstream-РёРЅСЃС‚СЂСѓРјРµРЅС‚ РЅРµ СЂР°Р±РѕС‚Р°РµС‚ РІ worktree) | **RESULT: OK** (РїРѕР»РёРіРѕРЅ/Р»РёРЅР·С‹/Р°СЃСЃРµС‚С‹/LF/РјР°СЂРєРµСЂС‹ WG СЃРѕС…СЂР°РЅРµРЅС‹) | `preflight-frozen-check.txt` |

## 3. РљР°РїС‡СѓСЂС‹ РґРѕ РІРєР»СЋС‡РµРЅРёСЏ (РґРёСЂРµРєС‚РёРІР° Рї.2; РєСЂРёС‚РµСЂРёРё (i)(ii)(iii), F5, F2/F4)

РџРѕР»РЅС‹Р№ РІС‹РІРѕРґ вЂ” `evidence/release-soul-25886/capture-before.txt` (read-only, РѕРґРёРЅ
SSH-РїСЂРѕРіРѕРЅ, Р±РµР· Р·Р°РїРёСЃРё РІ PG/СЂРµРїРѕ; СЃРµРєСЂРµС‚РѕРІ РЅРµС‚).

**PG-backup (РјР°СЂРєРµСЂ W2 F1.2 `composer_flag_release_gate`, РїСѓРЅРєС‚ (Р°)):** С„Р°Р№Р» РЅР°
СЃРµСЂРІРµСЂРµ `~/soul86_pg_backup_20261017T21вЂ¦Z.json` вЂ” 122 СЃС‚СЂРѕРєРё `bot_settings`
(`prompts.*`, `flags.*`, `character.*`, `style.*`, `humor.*`, `message.*`,
`expression.*`, `guide*`) + `chat_profiles` (3 С‡Р°С‚Р°, РІРєР»СЋС‡Р°СЏ overrides),
117 РљР‘, sha256_16 `253b548e650c1c2d`. Р—РЅР°С‡РµРЅРёСЏ РЅРµ РјСѓС‚РёСЂСѓСЋС‚СЃСЏ СЂРµР»РёР·РѕРј (РІС‹С‡РёСЃС‚РєР°
legacy вЂ” С‚РѕР»СЊРєРѕ РЅР° СЃР±РѕСЂРєРµ).

**(ii) РєР°СЃС‚РѕРјС‹ вЂ” РєРѕРЅС‚РµРЅС‚ СЃРЅСЏС‚ Р¶РёРІС‹Рј С‡С‚РµРЅРёРµРј, РІРµСЂРґРёРєС‚ РґР°РЅ:**
- `prompts.summary_editor_system_prompt`: sha12 **`6a1f3432889c`**, len **2023** вЂ”
  СЃРѕРІРїР°Р»Рѕ СЃ РѕР¶РёРґР°РЅРёРµРј R2 (`6a1f3432889c`/2023 в‡’ Р·РЅР°С‡РµРЅРёРµ СЃ РјРѕРјРµРЅС‚Р° СЃРЅР°РїС€РѕС‚Р° РЅРµ
  РјРµРЅСЏР»РѕСЃСЊ); РјР°СЂРєРµСЂС‹: Р±Р°Р·РѕРІС‹Рµ **0**, СЂР°СЃС€РёСЂРµРЅРЅС‹Р№ РЅР°Р±РѕСЂ (РґРІР°С‡/С…Р°СЂР°РєС‚РµСЂ Р±РѕС‚Р°/
  Р°С‚РјРѕСЃС„РµСЂ/СЃС‚Р°СЂС‹Р№ РіРѕР»РѕСЃ/persona/Р»РёС‡РЅРѕСЃС‚СЊ Р±РѕС‚Р°) вЂ” **0**; РєРѕРЅС‚РµРЅС‚ вЂ” СЂРµРґР°РєС‚РѕСЂСЃРєР°СЏ
  СЂРѕР»СЊ СЃР°РјРјР°СЂРё (В«РЎРРЎРўР•РњРќРђРЇ Р РћР›Р¬: РўС‹ вЂ” СЂРµРґР°РєС‚РѕСЂ СЃР°РјРјР°СЂРёвЂ¦В»), РёРЅСЃС‚СЂСѓРєС†РёР№ С…Р°СЂР°РєС‚РµСЂР°
  РЅРµС‚ в†’ **CLEAN** (РЅРµ СѓРґРµСЂР¶РёРІР°РµС‚СЃСЏ, РѕСЃС‚Р°С‘С‚СЃСЏ РґРµР№СЃС‚РІСѓСЋС‰РёРј вЂ” РєР°Рє Рё СЂРµС€РµРЅРѕ prep В§2).
- per-chat `prompts.summary_cover_style` (С‡Р°С‚ `-1002661910336`): sha12
  **`35013bd88081`**, len **110** вЂ” СЃРѕРІРїР°Р»Рѕ СЃ РѕР¶РёРґР°РЅРёРµРј R2; РјР°СЂРєРµСЂС‹ 0/0;
  РєРѕРЅС‚РµРЅС‚ вЂ” СЃС‚РёР»СЊ РѕР±Р»РѕР¶РєРё РєРѕРјРёРєСЃР° (В«Comic-book style, set in modern RussiaвЂ¦В»)
  в†’ **CLEAN** (РЅРµ СѓРґРµСЂР¶РёРІР°РµС‚СЃСЏ; РІ effective РЅРµ СѓС‡Р°СЃС‚РІСѓРµС‚ РєР°Рє Р»РёС‡РЅРѕСЃС‚СЊ).
- РєСЂРёС‚РµСЂРёР№ (ii) **Р·Р°РєСЂС‹С‚**: РєРѕРЅС‚РµРЅС‚ Р·Р°С…РІР°С‡РµРЅ, РІРµСЂРґРёРєС‚ В«С…Р°СЂР°РєС‚РµСЂРЅС‹С… РёРЅСЃС‚СЂСѓРєС†РёР№ РЅРµС‚В».

**F5 `personas`/`persona_traits` вЂ” РІРµСЂРґРёРєС‚: РєРѕРЅС„Р»РёРєС‚Р° СЃ Core РЅРµС‚ (РІ СЃРјС‹СЃР»Рµ
РёРЅСЃС‚СЂСѓРєС†РёР№ Р»РёС‡РЅРѕСЃС‚Рё), РЅРѕ РѕС‚РјРµС‡РµРЅРѕ С„Р°РєС‚РёС‡РµСЃРєРѕРµ СЃРѕСЃС‚РѕСЏРЅРёРµ:**
`personas`: 2 СЃС‚СЂРѕРєРё (РіР»РѕР±Р°Р»СЊРЅР°СЏ + С‡Р°С‚ `-1002661910336`) вЂ” `name`, `biography`,
`system_prompt_overrides` **РїСѓСЃС‚С‹Рµ** (sha12 РїСѓСЃС‚РѕР№ СЃС‚СЂРѕРєРё), С‚.Рµ. РїРµСЂСЃРѕРЅР°Р»СЊРЅРѕРіРѕ
РєРѕРЅС‚РµРЅС‚Р° РЅРµС‚; `persona_traits`: 50 СЃС‚СЂРѕРє (deep-sleep РЅР°Р±Р»СЋРґРµРЅРёСЏ РІРёРґР° В«РўРѕРЅ СЃС‚Р°Р»
Р±РѕР»РµРµ РІРѕР»СЊРЅС‹Рј Рё РґРµСЂР·РєРёРјвЂ¦В»), РјР°СЂРєРµСЂРѕРІ СЃС‚Р°СЂРѕР№ Р»РёС‡РЅРѕСЃС‚Рё **0**. РС‚РѕРі: СЃРєСЂС‹С‚С‹С…
РёРЅСЃС‚СЂСѓРєС†РёР№ С…Р°СЂР°РєС‚РµСЂР°, РєРѕРЅРєСѓСЂРёСЂСѓСЋС‰РёС… СЃ Core, РЅРµС‚ в†’ РєСЂРёС‚РµСЂРёР№ F5 Р·Р°РєСЂС‹С‚;
РїРѕРІРµРґРµРЅС‡РµСЃРєРёРµ С‡РµСЂС‚С‹ (AMD.4.6(iii), РІРѕРїСЂРѕСЃ РѕС‚РєСЂС‹С‚) РѕСЃС‚Р°СЋС‚СЃСЏ РєР°Рє РµСЃС‚СЊ.

**(i) СѓРґРµСЂР¶Р°РЅРёРµ:** PG-РєР»СЋС‡Рё SOUL (`flags.*`) РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‚ вЂ” **0**; РґРѕРєСѓРјРµРЅС‚С‹
`character.core`/`style.policy`/`humor.craft` РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‚ (`docs_present=[]`) вЂ”
СЌС‚Рѕ РѕР¶РёРґР°РµРјРѕРµ СЃРѕСЃС‚РѕСЏРЅРёРµ В«РґРѕ РІРєР»СЋС‡РµРЅРёСЏВ».

**F2:** `SMART_VERBALIZER_MODES_ENABLED` РІ `.env` вЂ” РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚; РїСЂРѕС†РµСЃСЃ-environ
РёР·-РїРѕРґ `nik` РЅРµ С‡РёС‚Р°РµС‚СЃСЏ (PermissionError, РѕР¶РёРґР°РµРјРѕ). Р”РµР№СЃС‚РІСѓРµС‚ РєРѕРґ-РґРµС„РѕР»С‚
`True` (`config/settings.py:568`, `_env_bool(..., True)`) в‡’ В«в‰  0В» РІС‹РїРѕР»РЅРµРЅРѕ;
code-fallback (PG down) РїСЂРёРЅСЏС‚ РєР°Рє OFF-РїР°СЂРёС‚РµС‚ W2 (СЂРµС€РµРЅРёРµ R2).

**F4:** env `NOSTALGIA_ENABLED` РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚ (settings-РґРµС„РѕР»С‚ `False`).
**РћС‚РєР»РѕРЅРµРЅРёРµ РѕС‚ РѕР¶РёРґР°РЅРёСЏ R2:** PG-РєР»СЋС‡ `memory.nostalgia_enabled` РЅР° РїСЂРѕРґРµ
**РїСЂРёСЃСѓС‚СЃС‚РІСѓРµС‚ Рё СЂР°РІРµРЅ `true`** (РІ СЃРЅР°РїС€РѕС‚Рµ 17.10 РµРіРѕ РЅРµ Р±С‹Р»Рѕ; СЂРµР»РёР·РѕРј РѕРЅ РЅРµ
СЃРѕР·РґР°С‘С‚СЃСЏ Рё РЅРµ РјРµРЅСЏРµС‚СЃСЏ). Р¤Р°РєС‚РёС‡РµСЃРєРѕРµ СЃРѕСЃС‚РѕСЏРЅРёРµ Р·Р°С„РёРєСЃРёСЂРѕРІР°РЅРѕ, СЃРѕСЃС‚РѕСЏРЅРёРµ
СЂРµР·РѕР»РІР° вЂ” В§5 (Р¶СѓСЂРЅР°Р»/Р¶РёРІРѕР№ РїСЂРѕС†РµСЃСЃ).

**РЎРѕСЃС‚РѕСЏРЅРёРµ РѕСЃРµР№ РґРѕ РІРєР»СЋС‡РµРЅРёСЏ (РґРѕРєР°Р·Р°С‚РµР»СЊСЃС‚РІРѕ РёР·РѕР»СЏС†РёРё В«РІСЃС‘ OFFВ»):** РІСЃРµ
env-РѕСЃРё РІ `.env` РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‚ (`None` Г—10), `soul_flags_present=0`,
`docs_present=[]`.


## 4. Р”РµРїР»РѕР№ Рё РІРєР»СЋС‡РµРЅРёРµ РѕСЃРµР№ (РёСЃРїРѕР»РЅРёРјР°СЏ РїСЂРѕС†РµРґСѓСЂР° В§4)

РџСЂРѕРіРѕРЅС‹: `recon.txt` (21:44:08Z), `deploy-run.txt` (РѕСЃРЅРѕРІРЅРѕР№, 21:51:07вЂ“21:57Z),
`first-attempt-health-miss.md` (РїРµСЂРІР°СЏ РїРѕРїС‹С‚РєР° 21:46 Рё РµС‘ РґРёР°РіРЅРѕР·).

**Р”РµРїР»РѕР№ (РІСЃС‘ OFF).** fetch origin в†’ `checkout -B release/soul1-2.58.86`
(HEAD `eafbe2e7вЂ¦`, `TRACKED_MOD_AFTER=0`, `DELTA_FILES=628`), sha256_12
Р°СЂС‚РµС„Р°РєС‚РѕРІ **12/12** == СЂР°СЃС‡С‘С‚РЅС‹Рј, РјР°СЂРєРµСЂС‹ (`APP_VERSION="2.58.86"`,
`REFRACT_APPJS=6`, SOUL-С„Р°Р№Р»С‹ present, F3-С„СЂР°Р·Р° present).
РџРµСЂРІС‹Р№ СЂРµСЃС‚Р°СЂС‚ СѓРїС‘СЂСЃСЏ РІ 90-СЃРµРєСѓРЅРґРЅРѕРµ health-РѕРєРЅРѕ: РїСЂРёР»РѕР¶РµРЅРёРµ РЅРµ РІС‹С…РѕРґРёС‚ РЅР° HTTP
РґРѕ Р·Р°РІРµСЂС€РµРЅРёСЏ РјРёРіСЂР°С†РёРѕРЅРЅРѕРіРѕ СЂР°РЅРЅРµСЂР°, Р° С€Р°Рі v36 РґРµР»Р°РµС‚ backup-guard
(`VACUUM INTO`) вЂ” РЅР° РїСЂРѕРґ-РѕР±СЉС‘РјРµ **153 СЃ** (Р¶СѓСЂРЅР°Р»: `migration backup-guard:
done in 153.0s`). РЎРєСЂРёРїС‚ РєРѕСЂСЂРµРєС‚РЅРѕ РѕС‚РєР°С‚РёР»СЃСЏ РЅР° Р±Р°Р·Сѓ (РїСЂРѕРґ РІСЃС‘ РІСЂРµРјСЏ Р±С‹Р» Р¶РёРІ РЅР°
2.58.85, `.env`/PG РЅРµ С‚СЂРѕРЅСѓС‚С‹); РїРѕСЃР»Рµ С„РёРєСЃР° РѕРєРЅР° РѕР¶РёРґР°РЅРёСЏ (10 РјРёРЅ РЅР° РјРёРіСЂР°С†РёСЋ +
5 РјРёРЅ health) РІС‚РѕСЂРѕР№ РїСЂРѕРіРѕРЅ РїСЂРѕС€С‘Р» С†РµР»РёРєРѕРј. РњРёРіСЂР°С†РёСЏ: `pending=[36]` в†’
`v36 applied in 0.1s | humor_samples_v36` в†’ `user_version=36` (SQLite,
`BOOK [(36,'humor_samples_v36'), вЂ¦]`) вЂ” Р°РґРґРёС‚РёРІРЅРѕ, РєР°Рє Рё РїР»Р°РЅРёСЂРѕРІР°Р»РѕСЃСЊ.

**Enablement (РѕРґРёРЅ graceful-СЂРµСЃС‚Р°СЂС‚ РЅР° РІРµСЃСЊ РЅР°Р±РѕСЂ).** `.env` (С€Р°Рі 1):
`UNIFIED_COMPOSER_ENABLED=1`, `HUMOR_CRAFT_ENABLED=1`, `HUMOR_LIBRARY_ENABLED=1`,
`HUMOR_FEEDBACK_ENABLED=1`, `INITIATIVE_DIAGNOSTICS_PUBLISH_ENABLED=1`
(Р±СЌРєР°Рї `.env` вЂ” `~/soul86_env_backup_20261017T215445Z`; `HUMOR_CANDIDATE_EVAL_ENABLED`
РЅРµ РІРєР»СЋС‡Р°Р»СЃСЏ). PG (jsonb-bool, РЅРµ СЃС‚СЂРѕРєРё): `flags.unified_composer_enabled`,
`flags.humor_craft_enabled`, `flags.humor_library_enabled`,
`flags.humor_feedback_enabled` = `true` (С‚РёРї `boolean`, РїРѕРґС‚РІРµСЂР¶РґРµРЅРѕ РїРѕРІС‚РѕСЂРЅС‹Рј
С‡С‚РµРЅРёРµРј); `flags.humor_candidate_eval_enabled` РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚ (F5: РѕСЃРё РЅРµС‚ СЌС„С„РµРєС‚Р°).
Р—Р°С‚РµРј **РѕРґРёРЅ** graceful-СЂРµСЃС‚Р°СЂС‚ (21:54:51) в†’ healthz `2.58.86` (24 СЃ).

**Р”РѕРєСѓРјРµРЅС‚С‹ (in-app, hot; С€С‚Р°С‚РЅС‹Рј API, РЅРµ SQL):**
- `character.core` вЂ” Factory Default = Р°РІС‚РѕСЂСЃРєРёР№ SOUL-02: `POST
  /api/speech/block/core.personality` СЃ С„Р°Р±СЂРёС‡РЅС‹Рј С‚РµРєСЃС‚РѕРј РёР· СЂРµРµСЃС‚СЂР° в†’
  `applied=true`, СЂРµРІРёР·РёСЏ `act:040581a3b4b0`, `provenance owner_edit persisted`,
  РІ PG `character.core` (РїРѕР»РЅС‹Р№ С‚РµРєСЃС‚ 2835 Р·РЅ., sha12 `040581a3b4b0`);
  РїРѕСЃР»Рµ Р·Р°РїРёСЃРё Core: `source=global`, `origin=owner_edit`, `level=full`,
  `reason=owner_setting`, `differs_from_factory=false`.
- `style.policy` вЂ” `POST /api/speech/style` РІРµСЂРЅСѓР» `applied=true, revision=1`,
  РЅРѕ РґРѕРєСѓРјРµРЅС‚ **РЅРµ РїРµСЂСЃРёСЃС‚РёР»СЃСЏ** (РґРµС„РµРєС‚ РЅР°Р№РґРµРЅ Р¶РёРІС‹Рј РїСЂРѕРіРѕРЅРѕРј вЂ” СЃРј. В§7.8 Рё
  `defect-style-policy-global-save.md`); РїРѕРІРµРґРµРЅС‡РµСЃРєРё СЌРєРІРёРІР°Р»РµРЅС‚РЅРѕ В«РїРѕР»РёС‚РёРєРё
  РЅРµС‚В» (РїСѓСЃС‚Р°СЏ Р·Р°РІРѕРґСЃРєР°СЏ РїРѕР»РёС‚РёРєР°), РѕСЃРё РЅРµ РјРµС€Р°РµС‚.
- РРЅРёС†РёР°С‚РёРІР°: `POST /api/config {"flags.initiative_diagnostics_publish_enabled":
  true}` в†’ `200 {"updated": [...]}` (hot; Р¶СѓСЂРЅР°Р» `[api] config updated | key=вЂ¦
  | by=5885953495`); СЂРµР°Р»СЊРЅР°СЏ РѕС‚РїСЂР°РІРєР° РІСЃС‘ СЂР°РІРЅРѕ С‚СЂРµР±СѓРµС‚ `confirm_publish`.

## 5. РџРѕСЃС‚-РґРµРїР»РѕР№ РїСЂРѕРІРµСЂРєРё

| РџСЂРѕР±Р° | Р РµР·СѓР»СЊС‚Р°С‚ |
|---|---|
| healthz (loopback, 443, РёР·РІРЅРµ) | `{"status":"ok","version":"2.58.86"}` Г—3 |
| `GET /api/speech/overview` (Р°РґРјРёРЅ) | 200; **gates: РІСЃРµ 10 ON** (`unified_composer_enabled`, `character_core_enabled`, `speech_style_policy_enabled`, `humor_library_enabled`, `humor_feedback_enabled`, `persona_enabled`, `character_layers_enabled`, `experience_lessons_enabled`, `smart_verbalizer_modes_enabled`, `response_plan_enabled`); `registry.blocks=89`, `version=soul1-w3-1`, `factory_set=7422c0385f7d` |
| В«Р’СЃРµ РёРЅСЃС‚СЂСѓРєС†РёРёВ» (`/api/speech/blocks`) | 89 Р±Р»РѕРєРѕРІ, **withheld=11** СЂРѕРІРЅРѕ С‚Рµ РєР»СЋС‡Рё РєР»Р°СЃСЃР° СѓРґРµСЂР¶Р°РЅРёСЏ (factcheck/summary/search/checkup/direct/youtube/webвЂ¦) вЂ” legacy-СЃР»РѕР№ РЅРµ Р°РєС‚РёРІРµРЅ, WARNING `persisted speech value withheld` РІ Р¶СѓСЂРЅР°Р»Рµ (13 СЃС‚СЂРѕРє) |
| **Core РІ СЃР±РѕСЂРєРµ СЂРµС‡РµРІС‹С… РїСѓС‚РµР№** (`POST /api/speech/try`, СЂРµР°Р»СЊРЅС‹Р№ РєРѕРјРїРѕР·РµСЂ, Р±РµР· LLM) | `layers_current=["channel_contract","channel_contract","core"]`; `layer_order=[вЂ¦, core, identity, self_model_traits, context_lessons, response_plan, expression, humor_craft, few_shot, style_policy_hint, channel_output]`; `versions.core="r1.040581a3b4b0"`, `core_detail="full:owner_setting"`; `conflicts=[]` |
| Inspector | 200 (СЃРЅРёРјРѕРє С…РѕРґР° РїСѓСЃС‚ вЂ” СЂРµР°Р»СЊРЅРѕРіРѕ С…РѕРґР° РїРѕСЃР»Рµ СЂРµСЃС‚Р°СЂС‚Р° РµС‰С‘ РЅРµ Р±С‹Р»Рѕ; СЌС‚Рѕ РѕР¶РёРґР°РµРјРѕ) |
| Р‘РѕС‚ РїСЂРёРЅРёРјР°РµС‚ СЃРѕРѕР±С‰РµРЅРёСЏ | `Run polling for bot @PERMsoc_bot id=8802473181` (Р¶СѓСЂРЅР°Р»), `[webapp] lifespan started | pg_available=True`, СЂРѕСѓС‚РµСЂС‹/РІРѕСЂРєРµСЂС‹ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅС‹, `MEDIA_PUBLICвЂ¦` РѕРє |
| РџСЂРѕР±С‹ HTTP (loopback) | `/healthz`,`/web/`,`/web/app.js`,`/web/static/app.css`,`/static/fullscreen-policy.js`,`/static/glass-refraction.js` в†’ 200; `/api/speech/overview`, `/api/memory/initiative-vitality`, `/api/speech/blocks` в†’ **401** (РјР°СЂС€СЂСѓС‚С‹ Р¶РёРІС‹, РЅРµ 404) |
| РЎС‚СЂР°РЅРёС†Р° `/web/` | `2.58.86` Г—15, SOUL-РјР°СЂРєРµСЂС‹ Г—4 |
| Р–СѓСЂРЅР°Р» | **0 ERROR/CRITICAL/Traceback** (РµРґРёРЅСЃС‚РІРµРЅРЅРѕРµ СЃРѕРІРїР°РґРµРЅРёРµ вЂ” СЃР»РѕРІРѕ В«tracebackВ» РІРЅСѓС‚СЂРё RuntimeWarning, СЃРј. В§7.8); graceful-СЃС‚РѕРїС‹ Р±Р°Р·С‹ Рё СЃС‚Р°СЂС‚ 2.58.86 С‡РёСЃС‚С‹Рµ; `NRestarts=0`, `ExecMainStatus=0`, active/running |
| SQLite | `user_version=36`, С‚Р°Р±Р»РёС†Р° `humor_samples` РµСЃС‚СЊ, РєРЅРёРіР° `schema_migrations` v36 |
| 29 READY_FOR_LIVE | СЃРј. `postdeploy-observations.md`: С‡Р°СЃС‚СЊ Р·Р°РєСЂС‹С‚Р° Р°РіРµРЅС‚СЃРєРё (РѕСЃРё/СѓРґРµСЂР¶Р°РЅРёРµ/Core-РІ-СЃР±РѕСЂРєРµ/РёРЅРёС†РёР°С‚РёРІРЅР°СЏ РІРёС‚СЂРёРЅР°), РѕСЃС‚Р°Р»СЊРЅРѕРµ вЂ” owner-СЃС†РµРЅР°СЂРёРё (СЂРµР°Р»СЊРЅС‹Р№ РєР»РёРµРЅС‚/С‡Р°С‚/СѓСЃС‚СЂРѕР№СЃС‚РІРѕ); СЃС‚СЂРѕРєРё РєР°СЂС‚ РЅРµ РјРµРЅСЏР»РёСЃСЊ |


## 6. РћС‚РєР°С‚

**РџРѕ РѕСЃСЏРј (Р±РµР· РѕС‚РєР°С‚Р° РєРѕРґР°, РёСЃРїРѕР»РЅРёРјР°СЏ РїСЂРѕС†РµРґСѓСЂР° В§4):**
- РёРЅРёС†РёР°С‚РёРІР°: `POST /api/config {"items":[{"key":"flags.initiative_diagnostics_publish_enabled","value":false}]}` вЂ” hot, РјРіРЅРѕРІРµРЅРЅРѕ;
- Core: В«Р’РµСЂРЅСѓС‚СЊ Р·Р°РІРѕРґСЃРєРѕР№ РІР°СЂРёР°РЅС‚В» Р±Р»РѕРєР° `core.personality` (hot) Р»РёР±Рѕ `CHARACTER_CORE_ENABLED=0` + graceful-СЂРµСЃС‚Р°СЂС‚ (env-РїРѕР»РѕРІРёРЅР°);
- Style: СЃР±СЂРѕСЃ РґРѕРєСѓРјРµРЅС‚Р° `style.policy` (hot) Р»РёР±Рѕ `SPEECH_STYLE_POLICY_ENABLED=0` + graceful-СЂРµСЃС‚Р°СЂС‚;
- РјР°СЃС‚РµСЂ/humor: СѓРґР°Р»РёС‚СЊ/РѕР±РЅСѓР»РёС‚СЊ СЃС‚СЂРѕРєРё РІ `.env` + graceful-СЂРµСЃС‚Р°СЂС‚ (РѕСЃРё РіР°СЃРЅСѓС‚ РЅРµР·Р°РІРёСЃРёРјРѕ РѕС‚ PG; С„РѕСЂРјСѓР»РёСЂРѕРІРєР° В«PG=false вЂ” hotВ» РЅРµРІРµСЂРЅР°);
- PG-РєР»СЋС‡Рё `flags.*`: `UPDATE вЂ¦ SET value='false'::jsonb` + graceful-СЂРµСЃС‚Р°СЂС‚ (РЅРµРєР°С‚Р°Р»РѕРіРѕРІС‹Рµ РєР»СЋС‡Рё РЅРµ hot).

**Р”РѕРєСѓРјРµРЅС‚С‹:** `character.core`/`style.policy` вЂ” СЃР±СЂРѕСЃ Рє С„Р°Р±СЂРёРєРµ (hot) Р»РёР±Рѕ РѕСЃС‚Р°РІРёС‚СЊ
(РІСЂРµРґ РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚: Р±РµР· РґРѕРєСѓРјРµРЅС‚Р° РґРµР№СЃС‚РІСѓРµС‚ Р·Р°РІРѕРґСЃРєР°СЏ СЂРµРґР°РєС†РёСЏ).

**РџРѕР»РЅС‹Р№ РѕС‚РєР°С‚ РєРѕРґР°:** `cd /var/www/admin_bot && git checkout release/win-glass-2.58.85
&& sudo systemctl restart admin_bot` в†’ healthz 2.58.85. SQLite-РјРёРіСЂР°С†РёСЏ v36
(`humor_samples`) Р°РґРґРёС‚РёРІРЅР°, СЃС‚Р°СЂР°СЏ РІРµСЂСЃРёСЏ РµС‘ РёРіРЅРѕСЂРёСЂСѓРµС‚; Р±Р°Р№С‚С‹ `prompts.*` РІ PG
РЅРµ РјСѓС‚РёСЂРѕРІР°Р»РёСЃСЊ, backup вЂ” `~/soul86_pg_backup_*.json`.

**Р“РѕС‚РѕРІРЅРѕСЃС‚СЊ:** rollback Р°РІС‚РѕРјР°С‚РёР·РёСЂРѕРІР°РЅ РІ РґРµРїР»РѕР№-СЃРєСЂРёРїС‚Рµ (РїСЂРё РЅРµРґРѕСЃС‚РёР¶РµРЅРёРё
healthz 2.58.86 РїРѕСЃР»Рµ Р»СЋР±РѕРіРѕ СЂРµСЃС‚Р°СЂС‚Р°: checkout Р±Р°Р·С‹ + СЃРЅСЏС‚РёРµ env-РѕСЃРµР№ +
PG-РєР»СЋС‡Рё `false` + СЂРµСЃС‚Р°СЂС‚ + health 2.58.85). РџРѕС‚СЂРµР±РѕРІР°Р»СЃСЏ/РЅРµ РїРѕС‚СЂРµР±РѕРІР°Р»СЃСЏ вЂ” В§4/В§5.


## 7. Р”РµРІРёР°С†РёРё Рё С‡РµСЃС‚РЅС‹Рµ С…РІРѕСЃС‚С‹

## 7. Девиации и честные хвосты

1. **node-число** (ожидание «84/85 + предсуществующий RED `round1025_design_tokens`»):
   факт — **87/87 OK** (RED существовал только на прод-линии WG-релиза; master-линия
   содержит согласованные тест+`app.js`). Показываю фактическое число.
2. **Периметр** — 3917 (не 3915): +2 теста F1/F3 из `72b91d6e` (отревьюены в R2).
3. **W6 speech e2e**: RED на закоммиченной фикстуре (снята до слайса W4), GREEN
   (`failures=0`, 8 вьюпортов + interactions) на фикстуре, пере-снятой штатным
   генератором. Файл `evidence/w6/api-fixture.json` **не менялся** (W6-эвиденс —
   отдельный проход): `w6-e2e-diagnosis.txt` + `fixture-regenerated-by-dump-script.json`.
4. **W2-SHELL e2e**: RED, **предсуществует на базе** `95526863` (A/B — идентичная
   сигнатура): регрессия слоя стекла WIN-GLASS-P0 (мобильный «Раздел: …▾» в
   «Аналитике» перекрыт карточкой; `elementFromPoint` = карточка, скриншоты).
   К SOUL-1 не относится, релиз не блокирует; предложена минимальная правка
   stacking + повтор прогона (`w2-shell-e2e-diagnosis.txt`).
5. **F4-фиксация**: env `NOSTALGIA_ENABLED` отсутствует (settings-дефолт False),
   но PG-ключ `memory.nostalgia_enabled=true` **с 2026-09-06** (pre-existing, не
   релизом создан; рядом `memory.dream_enabled=true`). Живой процесс **поднимает
   NostalgiaWorker** (журнал: `NostalgiaWorker started (tick=60min, silence=45min,
   max_per_day=3, aggressiveness=0.3)`). Это фактическое состояние прода до/после
   релиза (не менялось), копия идёт через Core+жанровую рамку (AMD.2.6 проверен).
6. **F2-фиксация**: `SMART_VERBALIZER_MODES_ENABLED` в `.env` отсутствует →
   действует код-дефолт `True` (`config/settings.py:568`, `_env_bool(..., True)`)
   ⇒ «≠ 0» выполнено; proc-environ — dotenv-значения не видны в `/proc/<pid>/environ`
   (загружаются в процесс через `load_dotenv()`), фиксация по `.env` + код-дефолту.
7. **upstream `frozen_check.py`** падает в worktree (`_find_repo` требует каталог
   `.git`); применён адаптер к базе (`frozen_check_25886.py`), RESULT: OK.
8. **ДЕФЕКТ, найденный живым прогоном (follow-up №1):
   глобальное сохранение `style.policy` — молчаливый no-op.** `POST
   /api/speech/style` (scope=global) отвечает `applied=true`, но документ не
   персистится: `services/style_policy.py:2275` вызывает **асинхронный**
   `ConfigCache.set` без `await` (журнал: `RuntimeWarning: coroutine
   'ConfigCache.set' was never awaited`; в PG строки `style.policy` нет).
   Чат-ветка работает (там `await`). Видимое следствие: выбор «Глобально» в
   «Стиле письма» показывает «Правила сохранены», правила пропадают после
   перезагрузки. Правка — 1 строка + регресс-тест с async-кэшем; правку в дерево
   релиза **не вносил** (deployed tip == отревьюенный кандидат; правка продукта
   требует ревью). Детали: `defect-style-policy-global-save.md`.
9. **Первый прогон деплоя** (health-miss из-за 90-секундного окна и 153-секундного
   `VACUUM INTO` backup-guard миграции v36) — авто-откат на базу сработал,
   прод был жив; разбор и фикс окна: `first-attempt-health-miss.md`.
10. **Честные хвосты**: 29 READY_FOR_LIVE остаются owner-сценариями (реальный
    Telegram-клиент/устройство/живой чат) — карты не менялись, леджер отдельно;
    W8/W9 (метрики/A-B) не в поставке; OQ-4…OQ-8 (`plans/owner_questions.md`) —
    политика custom/Core для внекаталожных путей, не блокируют.

