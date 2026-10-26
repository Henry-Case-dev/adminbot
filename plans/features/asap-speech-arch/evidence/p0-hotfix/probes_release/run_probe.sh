#!/usr/bin/env bash
# P0 release probe 86ef2a64 -- READ-ONLY, one-shot, no writes/restarts.
# Staging /tmp/p0rel: tarball extract; .env + local_database.db symlinked from prod.
STAGE=/tmp/p0rel
OUT=/tmp/p0rel_out
SRC=/var/www/admin_bot
PY=$SRC/venv/bin/python
TAR=/tmp/p0rel_stage.tgz
EXP_HARNESS=fcd6d703d31d9bb2c28187a55d93b8e90803db1fd885c3fcad16359b4cef1bed
EXP_ANALYZER=de9783ce2f685d23787d44a14b045f7d5d98c3d74677b854ff15503a957d43f8

echo "== PROBE_START $(date -u +%FT%TZ)"
echo "== PRECHECK"
echo "prod_head=$(git -C $SRC rev-parse HEAD 2>&1)"
echo "dirty_before=$(git -C $SRC status --porcelain 2>/dev/null | wc -l)"
echo "unit_before: $(systemctl show admin_bot -p ActiveState,NRestarts,ExecMainStatus,MainPID 2>&1 | tr '\n' ' ')"
echo "healthz_before=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 https://127.0.0.1/healthz 2>/dev/null)"
echo "db_before: $(stat -c '%Y %s' $SRC/local_database.db 2>&1)"

echo "== STAGING"
rm -rf $STAGE $OUT
mkdir -p $STAGE $OUT || { echo "STAGE_MKDIR_FAILED"; exit 90; }
tar -xzf $TAR -C $STAGE || { echo "STAGE_EXTRACT_FAILED"; exit 91; }
printf 'PROBE_COMMIT=86ef2a64d1a8ebba4b7738c7594e30ba3391c8a8\nSTAGE_TGZ_SHA256=6688b2266a25ac1cc08b99db8f329352897b86b897cc5f715d1ff00acd292a10\n' > $STAGE/PROBE_COMMIT
echo "stage_files=$(find $STAGE -type f | wc -l)"
HREM=$(sha256sum $STAGE/probes_full/harness_probe_full.py | cut -d' ' -f1)
AREM=$(sha256sum $STAGE/probes_full/analyze_l2_meta.py | cut -d' ' -f1)
echo "harness_sha_remote=$HREM"
echo "analyzer_sha_remote=$AREM"
[ "$HREM" = "$EXP_HARNESS" ] && echo "harness_sha_match=true" || echo "harness_sha_match=false"
[ "$AREM" = "$EXP_ANALYZER" ] && echo "analyzer_sha_match=true" || echo "analyzer_sha_match=false"
echo "== SERVICE_FILE_SHA"
for f in direct_chat_service direct_l1 chat_prompts prompt_style_blocks response_extent prompt_composer prompt_registry factcheck_service factcheck_orchestrator; do
  echo "sha services/$f.py = $(sha256sum $STAGE/services/$f.py | cut -c1-16)"
done

echo "== PYTEST_FACTCHECK (before symlinks; mocked DB only)"
cd $STAGE
timeout 240 $PY -m pytest tests/test_factcheck_media_2026_10_25.py -q --no-header -p no:cacheprovider > $OUT/pytest_factcheck.log 2>&1
echo "pytest_rc=$?"
tail -5 $OUT/pytest_factcheck.log

echo "== SYMLINKS"
ln -sfn $SRC/.env $STAGE/.env
ln -sfn $SRC/local_database.db $STAGE/local_database.db
ls -l $STAGE/.env $STAGE/local_database.db

echo "== AST_CHECK"
timeout 60 $PY $STAGE/probes_full/harness_probe_full.py --ast-check $STAGE/probes_full/harness_probe_full.py > $OUT/astcheck.log 2>&1
echo "ast_rc=$?"
tail -2 $OUT/astcheck.log

echo "== SELF_CHECK"
timeout 120 $PY $STAGE/probes_full/harness_probe_full.py --root $STAGE --self-check > $OUT/selfcheck.json 2>$OUT/selfcheck.err
echo "selfcheck_rc=$?"
$PY -c "import json;d=json.load(open('$OUT/selfcheck.json'));print('self_check=',d['self_check'],'passed=',sum(1 for v in d['results'].values() if v is True),'total=',len(d['results']));print('l1_canon=',d.get('code_l1_canon'))" 2>&1

run_case () {
  local label=$1; shift
  echo "== RUN $label START $(date -u +%T)"
  timeout 300 $PY $STAGE/probes_full/harness_probe_full.py "$@" --out $OUT/raw_$label.json > $OUT/stdout_$label.log 2> $OUT/stderr_$label.log
  echo "rc_$label=$?"
  echo "-- invalid/fatal: $(grep -h RUN_INVALID $OUT/stderr_$label.log 2>/dev/null | tail -c 300)"
}

run_case new_code_A  --root $STAGE --rag-source service --use-code-l1-canon --label new_code_A  --case A
run_case new_code_B  --root $STAGE --rag-source service --use-code-l1-canon --label new_code_B  --case B
run_case new_code_C  --root $STAGE --rag-source service --use-code-l1-canon --label new_code_C  --case C
run_case new_forced_A --root $STAGE --rag-source service --use-code-l1-canon --label new_forced_A --case A --force-plan research
run_case new_forced_B --root $STAGE --rag-source service --use-code-l1-canon --label new_forced_B --case B --force-plan research
run_case old_A --root $SRC --rag-source service --label old_A --case A
run_case old_B --root $SRC --rag-source service --label old_B --case B

echo "== META"
timeout 120 $PY $STAGE/probes_full/analyze_l2_meta.py --raw $OUT/raw_new_code_A.json $OUT/raw_new_code_B.json $OUT/raw_new_forced_A.json $OUT/raw_new_forced_B.json $OUT/raw_new_code_C.json > $OUT/meta_report.txt 2>&1
echo "meta_rc=$?"
cat $OUT/meta_report.txt
timeout 120 $PY $STAGE/probes_full/analyze_l2_meta.py --raw $OUT/raw_new_code_A.json $OUT/raw_new_code_B.json $OUT/raw_new_forced_A.json $OUT/raw_new_forced_B.json $OUT/raw_new_code_C.json --json > $OUT/meta_report.json 2>&1

echo "== SUMMARY_TABLE"
$PY - <<'PYEOF' > $OUT/summary_table.txt 2>&1
import json, glob, os
for p in sorted(glob.glob('/tmp/p0rel_out/raw_*.json')):
    d = json.load(open(p))
    pc = d.get('payload_counts') or {}
    tot = pc.get('total') or {}
    rag = d.get('rag') or {}
    core = d.get('core') or {}
    l1 = d.get('l1_plan') or {}
    out = {
      'raw': os.path.basename(p), 'case': d.get('case'), 'forced': d.get('forced'),
      'plan_source': d.get('plan_source'), 'mode': d.get('mode'),
      'act_raw': d.get('l1_act_raw'), 'act_norm': d.get('l1_act_normalized'),
      'act_rewritten': d.get('l1_act_rewritten'),
      'extent': (l1 or {}).get('extent'), 'structure': (l1 or {}).get('structure'),
      'tone': (l1 or {}).get('tone'), 'conf': (l1 or {}).get('confidence'),
      'analysis_predicate': d.get('analysis_predicate'),
      'invalid': d.get('invalid'), 'fatal': (d.get('fatal') or '')[:120],
      'stage_errors': d.get('stage_errors') or {},
      'core_chars': core.get('chars'), 'core_sha12': core.get('sha12'),
      'core_in_system': core.get('in_system'),
      'rag_source': d.get('rag_source'), 'rag_rows': rag.get('rows'),
      'rag_block_chars': rag.get('block_chars'),
      'rag_empty_reason': rag.get('rag_empty_reason'),
      'rag_empty_ok': rag.get('rag_empty_is_correct'),
      'after_self': rag.get('after_self_filter'), 'after_dedup': rag.get('after_dedup'),
      'rerank': rag.get('rerank'),
      'frequent': (d.get('expression_check') or {}).get('frequent_text'),
      'dir_total': tot.get('directive'), 'writer_total': tot.get('writer'),
      'no_meta_total': tot.get('no_meta'), 'closing_total': tot.get('closing'),
      'closing_sys': (pc.get('system') or {}).get('closing'),
      'no_meta_contract': d.get('no_meta_contract'),
      'inv_1x1': pc.get('invariant_1x1'), 'inv_0x0': pc.get('invariant_0x0'),
      'l2_chars': [r.get('chars') for r in d.get('l2_runs') or []],
      'l2_meta_flagged': (d.get('l2_meta') or {}).get('flagged'),
      'l2_meta_total': (d.get('l2_meta') or {}).get('total'),
      'pg_ro': (d.get('sources') or {}).get('pg_read_only'),
      'l1_canon': {k: d.get('l1_canon', {}).get(k) for k in
                   ('chars', 'sha12', 'canon_source', 'code_sha12', 'pg_sha12', 'pg_matches_code')},
    }
    print(json.dumps(out, ensure_ascii=False))
PYEOF
cat $OUT/summary_table.txt

echo "== CLOSING_CHECK"
$PY - <<'PYEOF' > $OUT/closing_check.txt 2>&1
import sys, json, glob, os
sys.path.insert(0, '/tmp/p0rel')
from services import prompt_style_blocks as psb
C = getattr(psb, 'NO_META_CLOSING_TEXT', '') or ''
print('closing_const_chars=%d' % len(C))
for p in sorted(glob.glob('/tmp/p0rel_out/raw_*.json')):
    d = json.load(open(p)); msgs = (d.get('payload') or {}).get('messages') or []
    user = next((m['content'] for m in msgs if m['role'] == 'user'), '')
    sysx = next((m['content'] for m in msgs if m['role'] == 'system'), '')
    name = os.path.basename(p)
    if not C:
        print(name, 'closing_constant_absent'); continue
    in_user = C in user
    print(name,
          'count_user=%d count_sys=%d' % (user.count(C), sysx.count(C)),
          'after_cq=%s' % (in_user and user.find(C) > user.find('</Current_Question>')),
          'ends_with=%s' % user.rstrip().endswith(C))
PYEOF
cat $OUT/closing_check.txt

echo "== POSTCHECK"
echo "dirty_after=$(git -C $SRC status --porcelain 2>/dev/null | wc -l)"
echo "unit_after: $(systemctl show admin_bot -p ActiveState,NRestarts,ExecMainStatus,MainPID 2>&1 | tr '\n' ' ')"
echo "healthz_after=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 https://127.0.0.1/healthz 2>/dev/null)"
echo "db_after: $(stat -c '%Y %s' $SRC/local_database.db 2>&1)"
echo "== SHA_LIST"
( cd $OUT && sha256sum * )
echo "== PROBE_DONE $(date -u +%FT%TZ)"
exit 0
