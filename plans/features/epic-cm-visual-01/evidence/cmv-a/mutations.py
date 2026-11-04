"""Мутационная проверка CMV-A: каждое утверждение должно ломаться.

Каждая мутация вносится точечной заменой, прогоняется соответствующий тест,
ожидается FAIL, затем файл восстанавливается `git checkout --`.
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
REPO = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\cmv-a-integration-e0ca8268f2b2-3843e3a5"
os.chdir(REPO)

NODE = "node"
SCENE = "tests/js/evol_cog_scene_test.js"
VISUAL = "tests/js/evol_cog_visual_test.js"

MUTATIONS = [
    ("M1 single-flight RAF", "web/app.js",
     "        if (!scene || scene.raf != null) return false;",
     "        if (!scene) return false;", SCENE),
    ("M2 observers disconnect", "web/app.js",
     "          if (scene.ro && typeof scene.ro.disconnect === 'function') {\n"
     "            try { scene.ro.disconnect(); } catch (e) { /* noop */ }\n"
     "          }\n"
     "          scene.ro = null;",
     "          scene.ro = null;", SCENE),
    ("M3 fit() вместо формулы обзора", "web/app.js",
     "          if (typeof net.moveTo === 'function') {\n"
     "            net.moveTo({ position: fit.position, scale: fit.scale,\n"
     "                         animation: anim });\n"
     "            return true;\n"
     "          }",
     "          if (typeof net.fit === 'function') { net.fit(anim); return true; }",
     SCENE),
    ("M4 мутация исходного узла", "web/static/cog-visual.js",
     "    var row = {\n      id: node.id,",
     "    node.title = '';\n    var row = {\n      id: node.id,", VISUAL),
    ("M5 fitScale не пересчитан", "web/app.js",
     "        this._cogRefreshFitScale();\n        this._cogRestoreCamera(false);",
     "        this._cogRestoreCamera(false);", SCENE),
    ("M6 зажим масштаба обзора", "web/app.js",
     "        var s = (typeof scale === 'number' && isFinite(scale) && scale > 0)\n"
     "          ? scale : 1;",
     "        var s = (typeof scale === 'number' && isFinite(scale) && scale > 0)\n"
     "          ? Math.max(0.15, scale) : 1;", SCENE),
]


def run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    return res.returncode, (res.stdout or "") + (res.stderr or "")


def main():
    results = []
    for name, path, old, new, test in MUTATIONS:
        full = os.path.join(REPO, path)
        src = open(full, encoding="utf-8").read()
        if old not in src:
            results.append((name, "SKIP-нет-точки", ""))
            continue
        open(full, "w", encoding="utf-8", newline="").write(src.replace(old, new, 1))
        try:
            code, out = run([NODE, test])
        finally:
            subprocess.run(["git", "checkout", "--", path], cwd=REPO)
        tail = [l for l in out.strip().splitlines() if l.strip()][-1:]
        results.append((name, "FAIL(jiста) -> тест упал" if code != 0 else "ПРОШЁЛ — дыра!",
                        (tail[0] if tail else "")[:120]))
    for name, verdict, tail in results:
        print("%-34s %s | %s" % (name, verdict, tail))
    holes = [r for r in results if "ПРОШЁЛ" in r[1] or "SKIP" in r[1]]
    print("MUTATION-HOLES=%d" % len(holes))
    return 1 if holes else 0


if __name__ == "__main__":
    sys.exit(main())
