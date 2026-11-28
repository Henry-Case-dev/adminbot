Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$wt = "C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\release-2-58-274-5aac2da8cc1c-63c506eb"
$raw = Join-Path $wt "plans\features\fc-trust-01\evidence\release-2.58.274\raw"
$py = "C:\Code\Python\adminbot\.venv\Scripts\python.exe"
Set-Location $wt

$head = git rev-parse HEAD
$tree = git rev-parse "$head^{tree}"
$branch = git rev-parse --abbrev-ref HEAD
$dirty = @(git status --porcelain --untracked-files=no).Count
$untracked = @(git status --porcelain --untracked-files=all | Where-Object { $_ -like '??*' })

$identity = @(
  "branch=$branch",
  "head=$head",
  "head_tree=$tree",
  "base_deploy_74ef57ef4=$(git rev-parse 74ef57ef4)",
  "base_branch_tip_2cbbea193=$(git rev-parse 2cbbea193)",
  "candidate_tip_320517373=$(git rev-parse 320517373)",
  "candidate_code_dc6703a8f=$(git rev-parse dc6703a8f)",
  "merge_commit_4b6b5279d=$(git rev-parse 4b6b5279d)",
  "bump_commit=$head",
  "dirty_tracked=$dirty",
  "dirty_untracked_count=$($untracked.Count)",
  "worktrees=$(@(git worktree list --porcelain | Select-String '^worktree ').Count)",
  "routes_blob=$(git hash-object web/api/routes.py) routes_blob_base=$(git rev-parse 74ef57ef4:web/api/routes.py)",
  "appjs_blob=$(git hash-object web/app.js) appjs_blob_base=$(git rev-parse 74ef57ef4:web/app.js)",
  "index_blob=$(git hash-object web/index.html) index_blob_base=$(git rev-parse 74ef57ef4:web/index.html)",
  "factcheck_py_blob=$(git hash-object handlers/factcheck.py) candidate_blob=$(git rev-parse dc6703a8f:handlers/factcheck.py)",
  "persistent_throttling_blob=$(git hash-object services/persistent_throttling.py) candidate_blob=$(git rev-parse dc6703a8f:services/persistent_throttling.py)",
  "smartmodule_throttling_blob=$(git hash-object services/smartmodule_throttling.py) candidate_blob=$(git rev-parse dc6703a8f:services/smartmodule_throttling.py)"
) -join "`n"
$identity | Set-Content -Path (Join-Path $raw "identity-predeploy.txt") -Encoding utf8

$manifest = [ordered]@{
  branch = $branch
  head = $head
  tree = $tree
  version = "2.58.274"
  dirty_tracked = ($dirty -gt 0)
  base = "2cbbea193"
  base_deploy = "74ef57ef4"
  base_version = "2.58.273"
  candidates = [ordered]@{ "fct-s4" = "320517373cc8185835f0011e5724d50eda12caf8" }
  candidate_code = "dc6703a8f77b11505f3fe8518960fadc9df806de"
  review = "plans/features/fc-trust-01/evidence/fct-s4-reliability-2026-11-28/review-r1.md (APPROVED_FOR_RELEASE_PREPARATION)"
  bump = "version-only, 29 files / 34 occurrences"
  merge = "4b6b5279da17f85bf2f5bbf8fa09619718ca10ea"
  routes_py_sha256 = "5c20750a0a273651600a2baf1fe0a74a842585742af1e1a846cf1f8ecff79bdf"
  app_js_sha256 = "20e87aa86fd888114ba706282021a4fcb10331e2672c0aec12d8b61f04b28e74"
  index_html_sha256 = "b8570e5deb8136756dba402719d9530d6e3ff4ed17a45f18ed0d99b001323907"
  ddl = 0
  schema = "unchanged"
}
$manifestJson = $manifest | ConvertTo-Json -Compress
$manifestJson | Set-Content -Path (Join-Path $raw "manifest-predeploy.txt") -Encoding utf8

Write-Output "--- identity ---"
$identity
Write-Output "--- manifest ---"
$manifestJson
Write-Output "--- untracked ---"
$untracked

