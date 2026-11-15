# VMQ-M2 Review R1 - Approved 
Candidate vmq/m2 delivery 8b56fc7320722494d0191f320e6da3355cc1a654 code f7a9c596638ea733de5673c5fd31675c746e20a7 base 64dab0eb756894ae700991931dddbf58ccd46bf4. 
Predeploy REVIEW only; production not accessed. 
Implementation audited retrieve to rag retrieve to unified rows to evidence bundle to Writer; same RetrievalResult and one bundle; no DDL writes embeddings or second router. 
Test validity all 21 bodies and assertions read; real in-memory DB EpisodeService SQL tracing negative cases. 
Independent challenge mutation forwarding overview true to false failed delivery assertion expected True actual False; restored. 
Checks focused 21 passed. Affected 727 passed 1 failed, pre-existing speech style anchors StopIteration. 
Ledger M-04 REVIEW approved; M-05 REVIEW approved; O-04 REVIEW approved. Never VERIFIED; live artifacts absent. 
Next PM bind and review gate; DevOps controlled preprod then live release gate.
 
Addendum 2026-11-15: controlled deployment decision 
M-04 and O-04 are legitimate postrelease waits. Required live evidence exercises the deployed L1/Writer process and cannot be obtained predeploy without changing the runtime under review. Predeploy implementation and test evidence is sufficient for controlled deployment; live acceptance remains pending. 
approved_postrelease_wait M-04: {nonblocking:true, reason:'preprod-only live Writer/person-overview and temporal proof requires the deployed process; no user message is needed', trigger:'after 2.58.204 is deployed at the candidate SHA, run agent-owned e2e for person-overview, temporal query, exact owner query, and current-state negative', next_check:'DevOps runs the four-case e2e, captures one retrieve/one bundle, coverage, independent_periods, counterexamples, limitations, and current-state negative; then run release gate', owner:'DevOps', contract_ref:'MAN-M-04 / requirements-map.json acceptance; m2-contract-confirmation-2026-11-15.md'} 
approved_postrelease_wait O-04: {nonblocking:true, reason:'one-route e2e and corrections/versioning must be observed through the deployed L1/Writer process', trigger:'same 2.58.204 deployed-process e2e, including exact owner query and a subsequent corrected/versioned query', next_check:'DevOps captures route trace showing one retrieve, one bundle, no second search/router/DB/LLM, and correction/version effect; then run release gate', owner:'DevOps', contract_ref:'MAN-O-04 / requirements-map.json acceptance; m2-contract-confirmation-2026-11-15.md'} 
Controlled deployment conditions: candidate must be the reviewed integrated release train, production baseline c97c06e4, target 2.58.204, DDL 0, rollback c97c06e4. Run health check and read-only agent e2e only; do not send a user message. 
Rollback: immediately restore c97c06e4 if health fails, any case lacks the required bundle fields, route count is not one, current-state negative leaks historical overview, or correction/version trace is absent or contradictory. 
Approval invalidated by any code or config change affecting these paths, failed predeploy gate, missing rollback, failed live e2e, cross-chat leak, extra retrieval/search/model call, or evidence not bound to deployed SHA. M-05 has no postrelease wait: predeploy negative evidence is complete.
