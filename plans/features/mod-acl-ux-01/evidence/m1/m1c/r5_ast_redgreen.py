"""RED/GREEN для R5-F02: новый самотест против старого (0a110a173) сканера.

Usage: python ast_redgreen.py <repo> <out-dir>
"""
import hashlib
import os
import subprocess
import sys

REPO = os.path.abspath(sys.argv[1])
OUT = os.path.abspath(sys.argv[2])
REL = "tests/test_mod_acl_ux_01_m1c_prompt_text_invariant.py"
PY = sys.executable

OLD_SCANNER = '''    #: Материализаторы/скоуп-API, которые web не имеет права вызывать.
    FORBIDDEN_ATTRS = {"system_scope", "_factory_text_raw",
                       "_effective_prompt_raw", "journal_write_scope",
                       "legacy_migration_write"}
    #: Кто единственный пишет scope (auth-time в deps, middleware в app).
    SCOPE_WRITE_ALLOWED = {"set_scope": {"web/api/deps.py", "web/app.py"},
                           "reset_scope": {"web/app.py"}}

    def _prompt_text_bindings(self, tree):
        """``{локальное имя: каноническое}`` для модуля и его членов."""
        aliases: dict[str, str] = {}
        direct: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name or ""
                    if mod == "services.prompt_text":
                        aliases[alias.asname or "prompt_text"] = \\
                            "services.prompt_text"
                    elif mod.startswith("services.prompt_text."):
                        attr = mod.rsplit(".", 1)[1]
                        direct[alias.asname or attr] = attr
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    asname = alias.asname or alias.name
                    if mod == "services.prompt_text":
                        direct[asname] = alias.name
                    elif mod == "services" and alias.name == "prompt_text":
                        aliases[asname] = "services.prompt_text"
                    elif mod == "services" \\
                            and alias.name in self.FORBIDDEN_ATTRS:
                        direct[asname] = alias.name
        return aliases, direct
'''

OLD_SCAN = '''    def _scan_offenders(self, tree, rel: str) -> list:
        """Нарушения файла: вызов сырого материализатора/неразрешённая запись scope."""
        aliases, direct = self._prompt_text_bindings(tree)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                real = direct.get(node.id)
                if real is not None and real in self.FORBIDDEN_ATTRS:
                    offenders.append((rel, real))
                if real is None:
                    real = node.id
                if real in self.SCOPE_WRITE_ALLOWED \\
                        and rel not in self.SCOPE_WRITE_ALLOWED[real]:
                    offenders.append((rel, real))
            elif isinstance(node, ast.Attribute) \\
                    and isinstance(node.value, ast.Name) \\
                    and node.value.id in aliases:
                if node.attr in self.FORBIDDEN_ATTRS:
                    offenders.append((rel, node.attr))
                if node.attr in self.SCOPE_WRITE_ALLOWED \\
                        and rel not in self.SCOPE_WRITE_ALLOWED[node.attr]:
                    offenders.append((rel, node.attr))
        return offenders
'''


def run_pytest():
    proc = subprocess.run(
        [PY, "-m", "pytest", REL, "-q", "-p", "no:cacheprovider",
         "--timeout=300", "-k", "alias_detector"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    return proc.stdout + proc.stderr


def main():
    path = os.path.join(REPO, REL)
    src = open(path, encoding="utf-8").read()
    start_marker = "    #: (модуль, запрещённые члены)"
    end_marker = '    @pytest.mark.parametrize("src,expected", ['
    start = src.index(start_marker)
    end = src.index(end_marker)
    mutated = src[:start] + OLD_SCANNER + "\n" + OLD_SCAN + "\n\n" + src[end:]
    before = hashlib.sha256(src.encode("utf-8")).hexdigest()
    open(path, "w", encoding="utf-8", newline="").write(mutated)
    red = run_pytest()
    open(path, "w", encoding="utf-8", newline="").write(src)
    after = hashlib.sha256(open(path, encoding="utf-8").read()
                           .encode("utf-8")).hexdigest()
    assert before == after, (before, after)
    green = run_pytest()
    log = (
        "# R5-F02: AST-детектор — RED на 0a110a173 (старый сканер), GREEN после фикса\n"
        "# команда: pytest tests/test_mod_acl_ux_01_m1c_prompt_text_invariant.py"
        " -k alias_detector\n"
        "# RED = новый самотест (13 форм) против сканера 0a110a173;"
        " GREEN = текущий сканер.\n"
        "# файл восстановлен, sha256 до/после мутации совпал: %s\n\n"
        "=== RED (сканер 0a110a173, новые формы) ===\n%s\n"
        "=== GREEN (сканер после R5-F02) ===\n%s\n" % (before, red, green)
    )
    open(os.path.join(OUT, "red-r5-ast.txt"), "w", encoding="utf-8",
         newline="").write(log)
    print("restored:", before == after)
    print([ln for ln in red.splitlines()
           if ln.startswith(("FAILED", "=====")) or "passed" in ln][-3:])
    print([ln for ln in green.splitlines()
           if ln.startswith(("FAILED", "=====")) or "passed" in ln][-3:])


main()
