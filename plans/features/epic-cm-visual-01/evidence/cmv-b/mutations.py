"""Мутационная проверка CMV-B: каждое утверждение должно ломаться.

Каждая мутация — точечная замена в рабочем дереве, прогон целевого node-теста,
ожидание FAIL, восстановление файла из сохранённой копии (git checkout в
общем worktree запрещён правилами проекта, поэтому копия — файл).

Запуск:
  .venv/Scripts/python.exe plans/features/epic-cm-visual-01/evidence/cmv-b/mutations.py
Код возврата 0 — дыр нет, 1 — какая-то мутация выжила.
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "..", ".."))
os.chdir(REPO)

NODE = "node"
SCENE = "tests/js/evol_cog_scene_test.js"
VISUAL = "tests/js/evol_cog_visual_test.js"
MAP = "tests/js/evol_cognitive_map_test.js"

# (имя, файл, что заменить, на что, тест)
MUTATIONS = [
    ("B1 форма: entity обратно в box", "web/static/cog-visual.js",
     "      evolution_event: { key: 'diamond', vis: 'diamond', decor: 'glint',",
     "      evolution_event: { key: 'diamond', vis: 'box', decor: 'glint',",
     VISUAL),
    ("B2 палитра: два типа одним цветом", "web/static/cog-visual.js",
     "        color: '#A77BFF', rim: 0.60 },",
     "        color: '#32C8F3', rim: 0.60 },", VISUAL),
    ("B3 свечение: дальний ореол ярче ближнего", "web/static/cog-visual.js",
     "      far: { ratio: 2.65, alpha: 0.10 },",
     "      far: { ratio: 2.65, alpha: 0.40 },", VISUAL),
    ("B4 спрайты: новый градиент на КАЖДЫЙ кадр", "web/static/cog-visual.js",
     "      var cached = sprites[spec.key];\n      if (cached) return cached;",
     "      var cached = null;", VISUAL),
    ("B5 импульсы вне реальных рёбер", "web/static/cog-visual.js",
     "        if (active && !reduced && frame.incident && frame.incident.length) {",
     "        if (active && !reduced && frame.nodes && frame.nodes.length) {\n"
     "          frame.incident = frame.nodes.slice(0, 3).map((n, i) => ({\n"
     "            id: 'x' + i, from: 'f1', to: n.id }));", VISUAL),
    ("B6 reduced-motion: время не выключено", "web/static/cog-visual.js",
     "        var now = reduced ? 0 : (frame.now || 0);",
     "        var now = (frame.now || 0);", VISUAL),
    ("B7 размер узла не зависит от degree", "web/static/cog-visual.js",
     "    var growth = CONFIG.node.degreeK * (Math.log(1 + deg) / Math.LN2);",
     "    var growth = 0;", VISUAL),
    ("B8 альфа рёбер: сплошные белые линии", "web/static/cog-visual.js",
     "      alphaByLod: [0.10, 0.13, 0.07],",
     "      alphaByLod: [0.95, 0.95, 0.95],", VISUAL),
    ("B9 физика: 150 итераций на 702 узлах", "web/static/cog-visual.js",
     "    if (n <= cfg.middleMax) return cfg.iterationsSmall;",
     "    return cfg.iterationsSmall;", VISUAL),
    ("B10 подписи: чёрная плашка вернулась", "web/app.js",
     "          ctx.strokeText(label.text, label.x, label.y);\n"
     "          ctx.fillStyle = selected ? cfg.selectedColor : cfg.color;",
     "          ctx.fillStyle = 'rgba(8,11,18,.72)';\n"
     "          ctx.fillRect(label.x - label.width / 2, label.y - 8,\n"
     "                       label.width, label.height);\n"
     "          ctx.fillStyle = selected ? cfg.selectedColor : cfg.color;", SCENE),
    ("B11 выбранный узел теряет подпись", "web/app.js",
     "        if (!alloc.labels.length && !forced.length) return 0;",
     "        forced.length = 0;\n"
     "        if (!alloc.labels.length && !forced.length) return 0;", SCENE),
    ("B12 кадр рисуется дважды за тик", "web/app.js",
     "        var visFresh = scene.visPaintedAt\n"
     "          && Math.abs(now - scene.visPaintedAt) < 17;",
     "        var visFresh = false;", SCENE),
    ("B13 пауза сцены не снимает кадр", "web/app.js",
     "        if (scene.paused) return false;",
     "        if (scene.paused) return true;", SCENE),
    ("B14 fx-канвас не сносится со сценой", "web/app.js",
     "          if (scene.fxCanvas && scene.fxCanvas.parentNode) {",
     "          if (false && scene.fxCanvas && scene.fxCanvas.parentNode) {",
     SCENE),
    ("B15 LOD подписей от абсолютного масштаба", "web/app.js",
     "            scale: r,",
     "            scale: cam.scale,", SCENE),
]


def run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    return res.returncode, (res.stdout or "") + (res.stderr or "")


def main():
    results = []
    for name, path, old, new, test in MUTATIONS:
        full = os.path.join(REPO, path)
        src = open(full, encoding="utf-8", newline="").read()
        if old not in src:
            results.append((name, "SKIP-нет-точки", ""))
            continue
        backup = src
        try:
            with open(full, "w", encoding="utf-8", newline="") as fh:
                fh.write(src.replace(old, new, 1))
            code, out = run([NODE, test])
        finally:
            with open(full, "w", encoding="utf-8", newline="") as fh:
                fh.write(backup)
        tail = [l for l in out.strip().splitlines() if l.strip()][-1:]
        verdict = ("FAIL(ожидаемо) → тест упал" if code != 0
                   else "ПРОШЁЛ — дыра!")
        results.append((name, verdict, (tail[0] if tail else "")[:110]))
    for name, verdict, tail in results:
        print("%-46s %s | %s" % (name, verdict, tail))
    holes = [r for r in results if "ПРОШЁЛ" in r[1] or "SKIP" in r[1]]
    print("MUTATION-HOLES=%d из %d" % (len(holes), len(results)))
    return 1 if holes else 0


if __name__ == "__main__":
    sys.exit(main())
