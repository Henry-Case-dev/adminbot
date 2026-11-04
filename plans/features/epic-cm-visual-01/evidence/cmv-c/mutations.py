"""Мутационная проверка CMV-C (LOD, агрегаты L0, подписи, счётчики).

Каждая мутация — точечная замена в рабочем дереве, прогон целевого node-теста,
ожидание FAIL, восстановление файла из сохранённой копии (git checkout в
общем worktree запрещён правилами проекта, поэтому копия — память).

Проверяется именно тот контракт, который заявлен в отчёте CMV-C:
  * LOD с гистерезисом и корректировкой по плотности (§4.2 контракта, §5.2 спеки);
  * приоритет подписей и отсутствие наложений в экранных координатах (§4.4);
  * агрегаты уровня 0 — реальные элементы, честные числа, обратимость (§5.2);
  * сцена: видимость L0, раскрытие района, счётчики §9.9.

Запуск:
  .venv/Scripts/python.exe plans/features/epic-cm-visual-01/evidence/cmv-c/mutations.py
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

MAPJS = "web/static/cognitive-map.js"
VISJS = "web/static/cog-visual.js"
APPJS = "web/app.js"

# (имя, файл, что заменить, на что, тест)
MUTATIONS = [
    # ── LOD ────────────────────────────────────────────────────────────────
    ("C1 LOD без гистерезиса (порог как есть)", MAPJS,
     "    var rise1 = t1 * (1 + d);",
     "    var rise1 = t1;", MAP),
    ("C2 LOD без гистерезиса на возврате", MAPJS,
     "    var fall1 = t1 * (1 - d);",
     "    var fall1 = t1;", MAP),
    ("C3 плотность не учитывается (нет обзора на 702)", MAPJS,
     "    var denseIn = denseMeasured && density >= densePer100k;",
     "    var denseIn = false;", MAP),
    ("C4 плотность возвращает в обзор при зуме", MAPJS,
     "    if (denseIn && value <= denseInRatio) return 0;",
     "    if (denseIn) return 0;", MAP),
    ("C5 сцена игнорирует плотность кадра", APPJS,
     "        var density = C.lodDensity(onScreen, scene.width, scene.height);",
     "        var density = null;", SCENE),
    # ── Подписи ────────────────────────────────────────────────────────────
    ("C6 выбранный узел теряет приоритет подписи", MAPJS,
     "    if (item.selected === true) return LABEL_RANK.selected;",
     "    if (item.selected === true) return LABEL_RANK.other;", MAP),
    ("C7 поиск не поднимает приоритет", MAPJS,
     "    if (item.search === true) return LABEL_RANK.search;",
     "    if (item.search === true) return LABEL_RANK.other;", MAP),
    ("C8 коллизии подписей отключены", MAPJS,
     "        if (boxesOverlap(box, placed[q], cfg.padding)) {",
     "        if (false && boxesOverlap(box, placed[q], cfg.padding)) {", MAP),
    ("C9 подписи районов не ставятся на уровень 0", APPJS,
     "              if (agg.count < minLabelCount) continue;",
     "              if (true) continue;", SCENE),
    # ── Агрегаты ───────────────────────────────────────────────────────────
    ("C10 агрегат теряет часть участников", MAPJS,
     "        memberIds: grp.nodeIds,",
     "        memberIds: grp.nodeIds.slice(1),", MAP),
    ("C11 число элементов района завышено", MAPJS,
     "        label: baseLabel + ' · ' + grp.count,",
     "        label: baseLabel + ' · ' + (grp.count + 1),", MAP),
    ("C12 центры районов не разводятся", MAPJS,
     "          var need = (ga.radius || 0) + (gb.radius || 0) + sepGap;",
     "          var need = 0;", MAP),
    ("C13 потоки считают несуществующие связи", MAPJS,
     "      if (!fromGroup || !toGroup || fromGroup === toGroup) continue;",
     "      if (!fromGroup || !toGroup) continue;", MAP),
    ("C14 узел без позиции получает «центр в нуле»", MAPJS,
     "      if (!p || numberOrNull(p.x) === null || numberOrNull(p.y) === null) continue;",
     "      if (!p) { p = { x: 0, y: 0 }; }", MAP),
    ("C15 уровень 0 скрывает ВСЕ узлы", APPJS,
     "        if (hide && !(scene.aggregates && scene.aggregates.length)) hide = false;",
     "        if (hide) hide = true;", SCENE),
    ("C16 выбранный узел скрывается LOD-ом", APPJS,
     "          var on = !hide || kept[id] === true || pinned[id] === true;",
     "          var on = !hide || kept[id] === true;", SCENE),
    ("C17 раскрытие района не уводит с уровня 0", APPJS,
     "        var floor = base > 0 ? base * 2.2 : scale;",
     "        var floor = base > 0 ? base * 1.05 : scale;", SCENE),
    ("C18 клик по району игнорирует узел под курсором", APPJS,
     "        if (scene.hoverId !== null && scene.hoverId !== undefined) return null;",
     "        if (false) return null;", SCENE),
    ("C19 ореолы скрытых узлов рисуются", VISJS,
     "          if (hiddenMap && hiddenMap[String(node.id)] === true) continue;",
     "          if (false && hiddenMap) continue;", VISUAL),
    # ── Счётчики и палитра ─────────────────────────────────────────────────
    ("C20 «в БД» подменяется «из API»", MAPJS,
     "    var dbNodes = null;",
     "    var dbNodes = apiNodes;", MAP),
    ("C21 палитра типов расходится со сценой", MAPJS,
     "    fact: { color: '#32C8F3', shape: 'dot', size: 14, legend: true },",
     "    fact: { color: '#38bdf8', shape: 'dot', size: 14, legend: true },", MAP),
    ("C22 сущности снова прямоугольники", MAPJS,
     "    entity: { color: '#9FB4CE', shape: 'sphere', size: 11, legend: false },",
     "    entity: { color: '#9FB4CE', shape: 'box', size: 11, legend: false },", MAP),
    # ── Ревью CMV-C: правки F1/F2 ──────────────────────────────────────────
    # F1: без полосы по r плотностная граница мигает (12 переключений на обходе).
    ("C23 плотностная граница без полосы по r (мигание)", MAPJS,
     "    var denseOutRatio = denseMax * (1 + d);",
     "    var denseOutRatio = denseMax;", MAP),
    # F1: без гистерезиса плотности кадр держит обзор до самого нуля.
    ("C24 плотность не отпускает обзор (нет 20 % полосы)", MAPJS,
     "    var denseOut = !denseMeasured\n      || density < densePer100k * numberOr(cfg.denseExitRatio,\n        DEFAULTS.lod.denseExitRatio);",
     "    var denseOut = !denseMeasured;", MAP),
    # F2: тема района снова берётся по алфавиту, а не по доминированию.
    ("C25 район назван недоминирующей парадигмой", MAPJS,
     "          && dominantShare >= 0.6 && paradigmShare >= 0.6) {",
     "          && dominantShare >= 0.6) {", MAP),
    ("C26 тема района = первая по алфавиту парадигма", MAPJS,
     "        if (titleCounts[titleKeys[tk]] > paradigmCount) {",
     "        if (paradigmTitle === null) {", MAP),
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
        results.append((name, verdict, (tail[0] if tail else "")[:120]))
    for name, verdict, tail in results:
        print("%-48s %s | %s" % (name, verdict, tail))
    holes = [r for r in results if "ПРОШЁЛ" in r[1] or "SKIP" in r[1]]
    print("MUTATION-HOLES=%d из %d" % (len(holes), len(results)))
    return 1 if holes else 0


if __name__ == "__main__":
    sys.exit(main())
