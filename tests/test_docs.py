"""Tests for the schema registry, the diagnostics and the generated docs."""

from __future__ import annotations

import argparse
import json

import pytest

from beanschedule import cli, schema

_DOCS_DIR = cli._docs_dir()


def _parsers():
    return cli._walk_commands(cli.build_parser(), ("beanschedule",))


def test_every_argument_has_help() -> None:
    for path, parser in _parsers():
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                continue
            if action.dest == "help":
                continue
            assert action.help, f"{' '.join(path)}: {action.dest} has no help"


def test_every_subcommand_has_help() -> None:
    for path, parser in _parsers():
        for action in parser._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for pseudo in action._choices_actions:
                assert pseudo.help, f"{' '.join(path)}: {pseudo.dest} has no help"


def test_render_docs_covers_expected_files() -> None:
    assert set(cli.render_docs()) == set(cli._GENERATED_FILES)


def test_generated_docs_match_disk() -> None:
    for name, content in cli.render_docs().items():
        path = _DOCS_DIR / name
        assert path.exists(), f"docs/{name} is missing"
        assert path.read_text(encoding="utf-8") == content, f"docs/{name} is stale"


def test_diagnostic_codes_are_unique() -> None:
    codes = [code.code for code in schema.DIAGNOSTIC_CODES]
    assert len(set(codes)) == len(codes)


def test_diagnostic_codes_are_complete() -> None:
    for code in schema.DIAGNOSTIC_CODES:
        assert code.summary
        assert code.explanation
        expected = {"E": schema.Severity.ERROR, "W": schema.Severity.WARNING}.get(
            code.code[:1]
        )
        assert expected is not None, f"{code.code} has an unknown prefix"
        assert code.severity is expected, f"{code.code} has the wrong severity"


def test_metadata_verbs_reference_real_keys() -> None:
    keys = {key.key for key in schema.METADATA_KEYS}
    for verb in schema.DIRECTIVE_VERBS:
        assert set(verb.metadata) <= keys


def test_render_message_unknown_code_raises() -> None:
    with pytest.raises(KeyError):
        schema.render_message("E999")


def test_schema_json_is_serialisable() -> None:
    assert json.loads(schema.dump_schema_json())["directive_verbs"]
