"""Мутационная проверка CMV-D (fullscreen, инспектор, счётчики, состояния).

Каждая мутация — точечная замена в рабочем дереве, прогон целевого теста,
ожидание FAIL, восстановление файла из копии в памяти (git checkout в общем
worktree запрещён правилами проекта).

Проверяется именно тот контракт, который заявлен в отчёте CMV-D:
  * раскладка заглушек без «комка» (спека §11, находка CMV-C);
  * счётчики БД/API/фильтр/экран не смешиваются (§9.9, CMV-NAV-07);
  * «Показана часть графа» и объяснение усечения (§2.2, CMV-ERR-05);
  * место показа инспектора: колонка/панель под сценой (§3.1/§8.2);
  * «Перейти» к соседу двигает камеру (§9, CMV-NAV-05);
  * свайп вниз по листу (§3.2, CMV-FSM-03);
  * смена чата и поздний ответ прошлого чата (§11, CMV-ERR-07);
  * возврат фокуса на кнопку открытия (§9, CMV-NAV-06);
  * имя кластера — частая парадигма (находка ревью CMV-C).

Запуск:
  .venv/Scripts/python.exe plans/features/epic-cm-visual-01/evidence/cmv-d/mutations.py
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
PY = sys.executable
D_TEST = "tests/js/evol_cmv_d_fullscreen_test.js"
MAP_TEST = "tests/js/evol_cognitive_map_test.js"
WIDGET_TEST = "tests/test_evol_cog_map_widget.py"

APPJS = "web/app.js"
MAPJS = "web/static/cognitive-map.js"
CSS = "web/static/app.css"
INDEX = "web/index.html"

# (имя, файл, что заменить, на что, чем проверять: node-файл или pytest)
MUTATIONS = [
    # ── раскладка заглушек: возврат «комка» ────────────────────────────────
    ("D1 узел снова встаёт в «центроид + 22/+22» (комок)",
     APPJS,
     "          if (!taken(x, y)) return { x: x, y: y };",
     "          return { x: cx + 22, y: cy + 22 };", D_TEST),
    # ── счётчики ───────────────────────────────────────────────────────────
    ("D2 «в базе» пропало — величины снова смешаны",
     APPJS,
     "        if (db.known === true) {",
     "        if (false) {", D_TEST),
    ("D3 «на экране» не отличается от фильтра",
     APPJS,
     "        var aggregated = screen.aggregated || 0;",
     "        var aggregated = 0;", D_TEST),
    # ── усечение ───────────────────────────────────────────────────────────
    ("D4 «Показана часть графа» выключено",
     APPJS,
     "        if (!active) return { active: false, hint: '' };",
     "        return { active: false, hint: '' };", D_TEST),
    # ── место показа инспектора ────────────────────────────────────────────
    ("D5 карточка всегда считается встроенной (слот не переключается)",
     APPJS,
     "        return this.graphFullVisible === true ? 'full' : 'embed';",
     "        return 'embed';", D_TEST),
    ("D6 встроенная карточка снова абсолютная (перекрывает узлы)",
     CSS,
     "    .cog-card--embed {\n      position: static;",
     "    .cog-card--embed {\n      position: fixed;", WIDGET_TEST),
    # ── навигация к соседу ─────────────────────────────────────────────────
    ("D7 «Перейти» не двигает камеру",
     APPJS,
     "            net.focus(nodeId, { scale: focusScale, animation: anim });",
     "            void focusScale;", D_TEST),
    # ── жесты листа ────────────────────────────────────────────────────────
    ("D8 свайп вниз всегда закрывает карточку (свернуть нельзя)",
     APPJS,
     "          if (this.cogCardSheetExpanded === true) this.cogCardSheetExpanded = false;\n"
     "          else this.closeCogCard();",
     "          this.closeCogCard();", D_TEST),
    # ── состояния: чат и поздний ответ ─────────────────────────────────────
    ("D9 смена чата не сбрасывает прежнюю модель",
     APPJS,
     "        this.cognitionGraphData = null;\n"
     "        this.cogCounts = null;\n"
     "        this._cogCountsSig = null;",
     "        this.cogCounts = null;\n"
     "        this._cogCountsSig = null;", D_TEST),
    ("D10 поздний ответ прежнего чата применяется",
     APPJS,
     "          if (gen !== (this._cogChatGen || 0) || chatId !== this.activeChatId) {",
     "          if (false) {", D_TEST),
    # ── фокус ──────────────────────────────────────────────────────────────
    ("D11 фокус не проверяется (отвязанный узел сходит за успех)",
     APPJS,
     "          return !!(active && (active === ref\n"
     "            || (ref.contains && ref.contains(active))));",
     "          return !!active;", D_TEST),
    # ── имя кластера ───────────────────────────────────────────────────────
    ("D12 кластер снова называется первым по алфавиту заголовком",
     MAPJS,
     "        if (cur === null || tkCount > paradigmCount\n"
     "            || (tkCount === paradigmCount\n"
     "              && (titleKeys[tk].length < cur.length\n"
     "                || (titleKeys[tk].length === cur.length\n"
     "                  && titleKeys[tk] < cur)))) {",
     "        if (cur === null) {", MAP_TEST),
    # ── состояние «данных нет»: прежний граф не остаётся ───────────────────
    ("D13 при отсутствии модели сцена не сносится (чужой граф на экране)",
     APPJS,
     "        if (!model) {\n"
     "          if (this.cognitionNetwork || this._cogScene) this.destroyCognitionGraph();",
     "        if (!model) {\n"
     "          if (false) this.destroyCognitionGraph();", D_TEST),
    # ── ошибка загрузки ────────────────────────────────────────────────────
    ("D14 отказ сети не показывается словами",
     APPJS,
     "        if (!err) return '';",
     "        if (true) return '';", WIDGET_TEST),
    # ── колонка инспектора и высота листа (раскладка §3.1/§3.2) ────────────
    ("D15 инспектор перестал быть колонкой (сцена не сужается)",
     CSS,
     "        grid-template-columns: minmax(0, 1fr) clamp(300px, 26vw, 360px);",
     "        grid-template-columns: minmax(0, 1fr);", WIDGET_TEST),
    ("D16 лист снова 52dvh вместо 35–45 % высоты",
     CSS,
     "        height: 40dvh; max-height: 85dvh;",
     "        height: 52dvh; max-height: 85dvh;", WIDGET_TEST),
    ("D17 телепорт карточки убран (слой остаётся вне слота)",
     INDEX,
     '<teleport v-if="cogCard" :to="cogCardSlot">',
     '<template v-if="cogCard">', WIDGET_TEST),
    # ── «Снять выбор» (CMV-CARD-06) ────────────────────────────────────────
    ("D18 «Снять выбор» больше не снимает выбор",
     APPJS,
     "      clearCogSelection: function () {\n        this._cogSelectedId = null;",
     "      clearCogSelection: function () {\n        void 0;", D_TEST),
]


def run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=600)
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
            if test.endswith(".py"):
                code, out = run([PY, "-m", "pytest", test, "-q", "-x"])
            else:
                code, out = run([NODE, test])
        finally:
            with open(full, "w", encoding="utf-8", newline="") as fh:
                fh.write(backup)
        tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:]
        verdict = ("FAIL(ожидаемо) → тест упал" if code != 0
                   else "ПРОШЁЛ — дыра!")
        results.append((name, verdict, (tail[0] if tail else "")[:120]))
    for name, verdict, tail in results:
        print("%-58s %s | %s" % (name, verdict, tail))
    holes = [r for r in results if "ПРОШЁЛ" in r[1] or "SKIP" in r[1]]
    print("MUTATION-HOLES=%d из %d" % (len(holes), len(results)))
    return 1 if holes else 0


if __name__ == "__main__":
    sys.exit(main())
