"""Tests for services/summary_aliases.py (T-181, R7/D61)."""
import logging

from services.summary_aliases import AliasResolver


class TestAliasResolver:
    def test_alias_wins(self):
        resolver = AliasResolver('{"123": "шеф"}')
        assert resolver.resolve(123, nickname="Коля", username="@kolya") == "шеф"

    def test_nickname_second(self):
        resolver = AliasResolver("{}")
        assert resolver.resolve(123, nickname="Николай", username="@kolya") == "Николай"

    def test_username_third_without_at(self):
        resolver = AliasResolver("")
        assert resolver.resolve(123, username="@kolya") == "kolya"

    def test_username_without_at_stays(self):
        resolver = AliasResolver("")
        assert resolver.resolve(123, username="kolya") == "kolya"

    def test_user_id_fallback(self):
        resolver = AliasResolver("")
        assert resolver.resolve(777, None, None) == "777"

    def test_empty_nickname_falls_through(self):
        resolver = AliasResolver("")
        assert resolver.resolve(5, nickname="", username="@u5") == "u5"

    def test_no_at_in_all_branches(self):
        resolver = AliasResolver('{"1": "@алиасик"}')
        assert "@" not in resolver.resolve(1)
        assert "@" not in resolver.resolve(2, nickname="@Ник")
        assert "@" not in resolver.resolve(3, username="@user")
        assert "@" not in resolver.resolve(4, None, None)

    def test_broken_json_returns_empty_dict(self, caplog):
        with caplog.at_level(logging.WARNING):
            resolver = AliasResolver("{не json")
        assert resolver.resolve(123, None, "@user") == "user"
        assert any("invalid JSON" in r.message for r in caplog.records)

    def test_non_dict_json_warns(self, caplog):
        with caplog.at_level(logging.WARNING):
            resolver = AliasResolver('["список"]')
        assert resolver.resolve(123, username="@x") == "x"
        assert any("not a JSON object" in r.message for r in caplog.records)

    def test_alias_for_string_key_user_id(self):
        resolver = AliasResolver('{"123": "чел"}')
        assert resolver.resolve(123, None, None) == "чел"

    def test_cache_used(self):
        resolver = AliasResolver("")
        first = resolver.resolve(9, nickname="Первый", username=None)
        second = resolver.resolve(9, nickname="Первый", username=None)
        assert first == second == "Первый"
        assert (9, "Первый", None) in resolver._cache
