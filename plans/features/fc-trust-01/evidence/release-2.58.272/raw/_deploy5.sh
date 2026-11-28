#!/usr/bin/env bash
# Release 2.58.272: prod-side blob/sha256 proof for every deployable file touched
# by the candidate, plus final cleanliness. Read-only.
set -u
APP=/var/www/admin_bot
cd "$APP" || { echo "ABORT_NO_APP_DIR"; exit 90; }

echo "== HEAD / CLEANLINESS =="
echo "HEAD=$(git rev-parse HEAD)"
echo "DIRTY_TRACKED=$(git status --porcelain --untracked-files=no | wc -l)"
echo "MANIFEST=$(tr -d '\n' < .deploy/release.json)"

echo "== BLOB IDS AT DEPLOYED HEAD =="
for p in web/api/routes.py web/app.js web/index.html config/settings.py \
         services/factcheck_orchestrator.py services/factcheck_prompts.py \
         tests/test_fc_trust_s6_aggregate_api.py tests/test_mca23_planned_vs_actual.py \
         tests/test_round1025_f8_registry.py tests/fixtures/round1025/f8_baseline.json; do
  echo "$(git rev-parse "HEAD:$p")  $p"
done

echo "== SHA256 OF DEPLOYED FILES =="
sha256sum tests/test_fc_trust_s6_aggregate_api.py tests/test_mca23_planned_vs_actual.py \
         tests/test_round1025_f8_registry.py tests/fixtures/round1025/f8_baseline.json \
         web/api/routes.py web/app.js web/index.html config/settings.py

echo "== EXPECTED (from assembly.md) =="
cat <<'EOF'
routes.py                         5c20750a0a273651600a2baf1fe0a74a842585742af1e1a846cf1f8ecff79bdf
app.js                            20e87aa86fd888114ba706282021a4fcb10331e2672c0aec12d8b61f04b28e74
index.html                        b8570e5deb8136756dba402719d9530d6e3ff4ed17a45f18ed0d99b001323907
settings.py                       ca3bc66df1c0b0de34f15b450d006c27a452c1e696e744c3801c2e79f44bdd7f
test_fc_trust_s6_aggregate_api.py f4ec5b1933ee3a2f9a304b35adc87be846a8a9ac5bf6fe298ce0b9612bba8050
test_mca23_planned_vs_actual.py   a155eb35e6737f1bf9c72c2e09ec8097f60ce189d4c73639baa37d72c2e32510
test_round1025_f8_registry.py     875d861eee1350ad3892b008a3124355a913a71ebe1a9077ad77ef46d934c0fb
f8_baseline.json                  3e22a537cb6d8f8f529d2d57c9a49422d8894301fb299215ad4d4b63283f563c
EOF

echo "== CLEANLINESS =="
echo "TMP_SCRATCH=$(ls /tmp/h.json /tmp/j*.txt /tmp/a*.js /tmp/appjs*.js /tmp/pubapp.js 2>/dev/null | wc -l)"
echo "WORKTREES=$(git worktree list | wc -l)"
echo "ORPHANS=$(pgrep -fc 'pytest|release_manifest.py --dry-run' || true)"
echo "== DONE5 =="
