"""Tests for the directive-carried config strings."""

from __future__ import annotations

from beanschedule import fava_ext
from beanschedule.config import parse_config


def test_parse_config_mapping_string() -> None:
    assert parse_config("{'forecast': True, 'months': 2}") == {
        "forecast": True,
        "months": 2,
    }


def test_parse_config_accepts_a_mapping() -> None:
    assert parse_config({"months": 1}) == {"months": 1}


def test_parse_config_rejects_non_mappings() -> None:
    assert parse_config("forecast") is None
    assert parse_config("") is None
    assert parse_config(None) is None
    assert parse_config("[1, 2]") is None
    assert parse_config("{not valid}") is None


def test_fava_write_setting() -> None:
    assert fava_ext._write_setting("{'write': True}") is True
    assert fava_ext._write_setting("{'write': 'custom.bean'}") == "custom.bean"
    assert fava_ext._write_setting("{}") is None
    assert fava_ext._write_setting(None) is None
    assert fava_ext._write_setting("not a mapping") is None


def test_fava_months_setting() -> None:
    assert fava_ext._months_setting("{'months': 2}") == 2
    assert fava_ext._months_setting("{}") == fava_ext._DEFAULT_MONTHS


def test_fava_plugin_config() -> None:
    options = {
        "plugin": [
            ("beancount.plugins.auto_accounts", None),
            (
                "beanschedule.plugin",
                "{'schedules_file': 's.bean', 'pending_file': 'p.bean'}",
            ),
        ]
    }
    assert fava_ext._plugin_config(options) == {
        "schedules_file": "s.bean",
        "pending_file": "p.bean",
    }
    assert fava_ext._plugin_config({}) == {}
    assert fava_ext._plugin_config({"plugin": [("other", "{}")]}) == {}


def test_fava_string_default() -> None:
    assert fava_ext._string("x", "d") == "x"
    assert fava_ext._string("", "d") == "d"
    assert fava_ext._string(None, "d") == "d"
