"""F2 (`urgent-summary-aliases-ui-round1022`, ADR-1022-2, UPD3):
рендер `limits.summary_aliases` — backend-гарантия объекта + cache-bust.

Проверяем (T-2028/T-2030/T-2033):
  * `_ensure_keyvalue_object` распаковывает строку-JSON (в т.ч. двойное
    кодирование) и не ломает прочие формы (список/скаляр → пустой объект);
  * served `index.html` версионирует `app.js` (`?v=APP_VERSION`);
  * статика `.js` отдаётся с `Cache-Control: no-store` (H3 stale JS).

Реальное поведение KV-редактора — в `tests/js/round1022_aliases_test.js`
(node → `ALIASES-UNIT-OK`).
"""
import json

from config.settings import APP_VERSION
from web.api import routes as routes_mod
from web.app import CacheControlStaticFiles, _render_index


class TestEnsureKeyvalueObject:
    def test_object_passthrough(self):
        src = {"1": "Иван"}
        assert routes_mod._ensure_keyvalue_object(src) == src

    def test_json_string_unpacked(self):
        src = {"1": "Иван"}
        assert routes_mod._ensure_keyvalue_object(
            json.dumps(src)) == src

    def test_double_encoded_unpacked(self):
        src = {"138811255": "Леха"}
        assert routes_mod._ensure_keyvalue_object(
            json.dumps(json.dumps(src))) == src

    def test_list_becomes_empty(self):
        assert routes_mod._ensure_keyvalue_object([1, 2]) == {}

    def test_non_json_string_becomes_empty(self):
        assert routes_mod._ensure_keyvalue_object("не json") == {}

    def test_none_becomes_empty(self):
        assert routes_mod._ensure_keyvalue_object(None) == {}


class TestCacheBust:
    def test_index_versions_app_js(self):
        html = _render_index()
        assert f"/web/app.js?v={APP_VERSION}" in html
        assert "__APP_VERSION__" not in html

    def test_js_static_is_no_store(self):
        assert ".js" in CacheControlStaticFiles._NO_CACHE_SUFFIXES
