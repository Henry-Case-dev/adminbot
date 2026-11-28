"""Канонический контракт версии (без литерала текущего номера в тестах).

Единственный источник истины — `config.settings.APP_VERSION`. Тесты,
которые раньше пинили конкретный номер (`== "2.58.N"`), проверяют здесь
согласованность всех компонентов, публикующих версию:

  * литерал в `config/settings.py` совпадает с импортированным runtime-
    значением (нет второго источника);
  * формат версии валиден (`MAJOR.MINOR.PATCH`, только цифры);
  * release-метаданные каталога (`plans/docs/param-registry-round1025.meta.md`)
    называют ту же версию;
  * индекс Mini App использует runtime-подстановку `__APP_VERSION__`
    (не захардкоженный номер).

Bump версии больше не требует правок тестов: они проверяют согласованность,
а не конкретное число. Реальные version-контракты (формат, `next_patch`,
манифест релиза) остаются в `tests/test_release_manifest.py`.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "config" / "settings.py"
META_PATH = ROOT / "plans" / "docs" / "param-registry-round1025.meta.md"
INDEX_PATH = ROOT / "web" / "index.html"

_VERSION_RE = re.compile(r'^APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"', re.MULTILINE)
_META_RE = re.compile(r"\*\*APP_VERSION:\*\*\s*`(\d+\.\d+\.\d+)`")


def declared_version() -> str:
    match = _VERSION_RE.search(SETTINGS_PATH.read_text(encoding="utf-8"))
    assert match, "APP_VERSION не найден в config/settings.py"
    return match.group(1)


def assert_version_contract() -> None:
    from config.settings import APP_VERSION

    runtime = APP_VERSION
    assert re.fullmatch(r"\d+\.\d+\.\d+", runtime), (
        "APP_VERSION имеет невалидный формат: %r" % (runtime,))
    assert runtime == declared_version(), (
        "runtime APP_VERSION %r != литерал config/settings.py %r — "
        "второй источник версии" % (runtime, declared_version()))
    meta_match = _META_RE.search(META_PATH.read_text(encoding="utf-8"))
    assert meta_match, "APP_VERSION отсутствует в release-метаданных каталога"
    assert meta_match.group(1) == runtime, (
        "release-метаданные называют %r, runtime — %r"
        % (meta_match.group(1), runtime))
    index = INDEX_PATH.read_text(encoding="utf-8")
    assert "__APP_VERSION__" in index, (
        "index.html не использует runtime-подстановку __APP_VERSION__")
