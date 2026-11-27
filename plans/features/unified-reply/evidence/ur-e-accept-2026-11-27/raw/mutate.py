import io
import os

DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\ur-e-accept-1ef96b25076e-1e7769b0"
src = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()

ORDER_OLD = "mod_direct: ['overview', 'inspector', 'settings', 'synthesizer',"
ORDER_NEW = "mod_direct: ['inspector', 'overview', 'settings', 'synthesizer',"
m1 = src.replace(ORDER_OLD, ORDER_NEW)
assert m1 != src, "mutation1 not applied"
io.open(os.path.join(DIR, "app_mut_order.js"), "w", encoding="utf-8").write(m1)

LABEL_OLD = "      overview: 'Как бот отвечает',"
LABEL_NEW = "      overview: 'Все настройки',"
m2 = src.replace(LABEL_OLD, LABEL_NEW)
assert m2 != src, "mutation2 not applied"
io.open(os.path.join(DIR, "app_mut_label.js"), "w", encoding="utf-8").write(m2)

print("mutations written:", DIR)
