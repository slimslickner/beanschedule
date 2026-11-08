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


def test_fava_write_setting_from_string() -> None:
    config = "{'write': 'Schedules.bean', 'months': 2}"
    assert fava_ext._write_setting(config) == "Schedules.bean"
    assert fava_ext._months_setting(config) == 2


def test_fava_settings_default() -> None:
    assert fava_ext._write_setting(None) is None
    assert fava_ext._write_setting("not a mapping") is None
    assert fava_ext._months_setting("{}") == fava_ext._DEFAULT_MONTHS
