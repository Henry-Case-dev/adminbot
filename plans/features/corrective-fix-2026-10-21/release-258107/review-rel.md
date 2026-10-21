# REVIEW REL-258107 (candidat 3a178c6c, baza dad9afce = prod 2.58.106), 22.10.2026

**Verdict: Approved -> DevOps.**

## Sostav
- git log dad9afce..HEAD = rovno 8 commits: factcheck 97818475+50c825ab (FC-R1, cfg-map), corrective 47522e7b/44a4827a/d8bade8d/4d9fd4be/bbcafef5, bump 3a178c6c. Drugih runtime-commitov net.
- Oba review-artefakta sushchestvuyut s Approved: review-fc-r1.md (REV-FACTCHECK-R1, -> 97818475+50c825ab), review-corrective-r1.md (REV-CORRECTIVE-R1, -> bbcafef5 volna).
- Runtime-delta = zayavlennyj nabor services (factcheck orchestrator/planner/temporal/search_aggregator/renderer/service; direct chat_prompts/direct_l1/direct_chat_service; mca_expression; nostalgia_prompts/nostalgia_worker; prompt_registry/prompt_migrations/prompt_style_blocks + canon-prompty) + tests + canon-doki + bump. web/ handlers/ migrations/ = 0. deltaDDL=0, schema v37 (ddl-check PASSx4; prompt_migrations bez DDL-tokenov).

## Kanonnaya bezopasnost (glavnyj risk)
- FACTORY_SET c19d35a1c093 vosproizveden NEZAVISIMO: 89 fabrichnyh kanonov cherez prompt_registry.factory_texts(), svoya sort/join/sha-tsep (bez vyzova ih factory_set_fingerprint) -> rovno c19d35a1c093 == konstanta == runtime.
- PREV-lestnicy polny: vse 7 PREV_*_CFG07A, PREV_NOSTALGIA_*_1021, PREV_DIRECT_L1_PLANNER_1021 (99a207313889711d/2423 = prod-yakor, novyj kanon 5fdc90b3f114/3022 - SIM2), PREV_TYPOGRAPHY_BLOCK; ROLLBACK_MIGRATIONS pokryvaet 7 kanonnyh klyuchej (prompt_migrations.py:297-324). Starye rubezhi ne poteryany.
- Gvard superseded-core vosproizveden (SIM1): PG-dok s baytami PREV-core -> superseded_fields=(full_text,), deystvuet novaya zavodskaya redakciya; kastom vladeltsa ne podmenyaetsya (SIM1b). PG-voskreshenie isklyucheno.
- Nostalgia-kanon: modul == registry factory text, be0452c55a32 (SIM3). Deploy-simulyaciya vosproizvedena po 3 kanonam.

## Privacy
- Suppress-mashina (custom_clean, prompt_registry:1629/prompt_factory:651) na meste; chistka bayt na sborke, hranimyy tekst ne menyaetsya. Testy custom_suppress + expression_isolation + registry_legacy_removal zelenye (77+91 passed u menya). §18G.3 allowlist tsel: renderer beret URL tolko iz EvidenceMap tekushchego progona; fc-testy zelenye.

## Gvardy (vosproizvedeno mnoy)
- F8 --check: CHECK OK 582==REGISTRY (zapusk instrumenta); help-sync 24p; write_points 1p; factcheck fc_r1_fix 22p; corrective L1/expression/nostalgia zelenye; JS node --check 107/0 (sweep); fingerprint runtime==constant. pins24 868p/0f - prinyat log (SET EQUAL proc-106, delta-vs-106.txt). Bump-verify: 31 fayl/33 pary, CHECK OK.

## Gigiena i sekrety
- Sekret-skan diffa dad9afce..3a178c6c (8 patternov): 0 popadaniy. Chuzhoy dirty (284 fayla) ne v kommitah; bump-set 31 fayl SET EQUAL proc-106, foreign-guard PASS.

## Riski deploya
- deltaDDL=0 -> otkat = checkout release/fix-2.58.106; vetki eshche net - SOZDAT pri deploye ot dad9afce (prod-HEAD dad9afce podtverzhden soul-1 evidence deploy.json).
- Starye persisted-kastomy vladeltsa ne postradayut: 7 klyuchey = lestnicy + ROLLBACK + suppress 3/11/14; kastomnye bayty gvard ne trogaet.
- RESTART PLANOVYY OBYAZATELEN (DevOps): FACTORY_SET - runtime-konstanta processa, goryachee primenenie kanonov nevozmozhno.

## Postdeploy-plan (obyazatelnyy, read-only)
1. healthz -> 2.58.107. 2. L1_PLAN telemetriya 48ch (react/silent dolya - nablyudenie, ne geyt). 3. expression_diag pri sleduyushchikh zhivykh vyzovakh. 4. Faktchek - sleduyushchiy realnyy run po novym marshrutam (traces). 5. Blob-sverki web ne nuzhny (web ne menialsya). 6. Rollback = release/fix-2.58.106.

## Blokery
- Net.
