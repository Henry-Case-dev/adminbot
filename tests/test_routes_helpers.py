"""Epic 85 (T-645) — тесты хелперов web/api/routes.py без HTTP.

_coerce_value: конвертация значений по типу каталога (bool/int/float/json/str)
и отказы (422-прецеденты); _mask_secret: пустое значение → not configured.
"""
import pytest

from web.api.routes import _coerce_value, _mask_secret


def _spec(typ):
    from services.param_catalog import ParamSpec
    return ParamSpec("X_FIELD", "X_FIELD", "limits", "t", typ)


class TestCoerceValue:
    def test_null_raises(self):
        with pytest.raises(ValueError):
            _coerce_value(_spec("str"), None)

    def test_bool_from_bool_str_int(self):
        assert _coerce_value(_spec("bool"), True) is True
        assert _coerce_value(_spec("bool"), "false") is False
        assert _coerce_value(_spec("bool"), "TRUE") is True
        assert _coerce_value(_spec("bool"), 1) is True
        assert _coerce_value(_spec("bool"), 0) is False

    def test_bool_from_garbage_raises(self):
        with pytest.raises(ValueError):
            _coerce_value(_spec("bool"), "yes")
        with pytest.raises(ValueError):
            _coerce_value(_spec("bool"), 2)

    def test_int(self):
        assert _coerce_value(_spec("int"), 42) == 42
        assert _coerce_value(_spec("int"), "42") == 42
        assert _coerce_value(_spec("int"), "-7") == -7

    def test_int_from_bool_or_garbage_raises(self):
        with pytest.raises(ValueError):
            _coerce_value(_spec("int"), True)
        with pytest.raises(ValueError):
            _coerce_value(_spec("int"), "42x")

    def test_float(self):
        assert _coerce_value(_spec("float"), 1.5) == 1.5
        assert _coerce_value(_spec("float"), 2) == 2.0
        assert _coerce_value(_spec("float"), "3.25") == 3.25

    def test_float_from_bool_or_garbage_raises(self):
        with pytest.raises(ValueError):
            _coerce_value(_spec("float"), True)
        with pytest.raises(ValueError):
            _coerce_value(_spec("float"), "нет")

    def test_json(self):
        assert _coerce_value(_spec("json"), {"a": 1}) == {"a": 1}
        assert _coerce_value(_spec("json"), [1, 2]) == [1, 2]
        assert _coerce_value(_spec("json"), (1, 2)) == (1, 2)
        assert _coerce_value(_spec("json"), '{"a": 1}') == {"a": 1}
        assert _coerce_value(_spec("json"), "не json") == "не json"

    def test_str(self):
        assert _coerce_value(_spec("str"), "текст") == "текст"
        assert _coerce_value(_spec("str"), 42) == "42"   # число → строка


class TestMaskSecret:
    def test_empty_value(self):
        assert _mask_secret("", 1, "keys.groq_api_key", None) == {
            "configured": False, "last4": None}
