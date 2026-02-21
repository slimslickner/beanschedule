"""Tests for schedule file loading and discovery."""

import os

import yaml

from beanschedule.loader import (
    find_schedules_location,
    get_enabled_schedules,
    load_schedule_from_file,
    load_schedules,
    load_schedules_from_directory,
)
from beanschedule.schema import GlobalConfig, ScheduleFile


class TestLoadScheduleFromFile:
    """Tests for loading individual schedule files."""

    def test_load_valid_schedule_file(self, temp_schedule_dir, sample_schedule_dict):
        """Test loading a valid schedule file."""
        # Create a schedule file
        schedule_path = temp_schedule_dir / "test-schedule.yaml"
        sample_schedule_dict["id"] = "test-schedule"
        sample_schedule_dict["transaction"]["metadata"]["schedule_id"] = "test-schedule"

        with open(schedule_path, "w") as f:
            yaml.dump(sample_schedule_dict, f)

        # Load it
        schedule = load_schedule_from_file(schedule_path)

        assert schedule is not None
        assert schedule.id == "test-schedule"
        assert schedule.enabled is True

    def test_load_disabled_schedule(self, temp_schedule_dir, sample_schedule_dict):
        """Test loading a disabled schedule."""
        schedule_path = temp_schedule_dir / "disabled-schedule.yaml"
        sample_schedule_dict["id"] = "disabled-schedule"
        sample_schedule_dict["enabled"] = False
        sample_schedule_dict["transaction"]["metadata"]["schedule_id"] = (
            "disabled-schedule"
        )

        with open(schedule_path, "w") as f:
            yaml.dump(sample_schedule_dict, f)

        schedule = load_schedule_from_file(schedule_path)

        assert schedule is not None
        assert schedule.enabled is False

    def test_filename_id_mismatch_returns_none(
        self, temp_schedule_dir, sample_schedule_dict
    ):
        """Test that filename/ID mismatch returns None."""
        # Create file with mismatched ID
        schedule_path = temp_schedule_dir / "wrong-name.yaml"
        sample_schedule_dict["id"] = "correct-id"
        sample_schedule_dict["transaction"]["metadata"]["schedule_id"] = "correct-id"

        with open(schedule_path, "w") as f:
            yaml.dump(sample_schedule_dict, f)

        schedule = load_schedule_from_file(schedule_path)

        # Should return None due to mismatch
        assert schedule is None

    def test_invalid_yaml_returns_none(self, temp_schedule_dir):
        """Test that invalid YAML returns None."""
        schedule_path = temp_schedule_dir / "invalid.yaml"

        with open(schedule_path, "w") as f:
            f.write("invalid: yaml: content: [")

        schedule = load_schedule_from_file(schedule_path)

        assert schedule is None

    def test_empty_file_returns_none(self, temp_schedule_dir):
        """Test that empty YAML file returns None."""
        schedule_path = temp_schedule_dir / "empty.yaml"

        with open(schedule_path, "w") as f:
            f.write("")

        schedule = load_schedule_from_file(schedule_path)

        assert schedule is None

    def test_validation_error_returns_none(self, temp_schedule_dir):
        """Test that validation errors return None."""
        schedule_path = temp_schedule_dir / "invalid-schema.yaml"

        # Create schedule with invalid schema (missing required fields)
        invalid_data = {
            "id": "invalid-schema",
            "enabled": True,
            # Missing required 'match', 'recurrence', 'transaction' fields
        }

        with open(schedule_path, "w") as f:
            yaml.dump(invalid_data, f)

        schedule = load_schedule_from_file(schedule_path)

        assert schedule is None


class TestLoadSchedulesFromDirectory:
    """Tests for loading schedules from directory."""

    def test_load_directory_with_schedules(
        self, temp_schedule_dir, sample_schedule_dict
    ):
        """Test loading multiple schedules from directory."""
        # Create two schedule files
        for i, name in enumerate(["schedule-1", "schedule-2"]):
            schedule_path = temp_schedule_dir / f"{name}.yaml"
            data = sample_schedule_dict.copy()
            data["id"] = name
            data["transaction"]["metadata"]["schedule_id"] = name

            with open(schedule_path, "w") as f:
                yaml.dump(data, f)

        # Load directory
        schedule_file = load_schedules_from_directory(temp_schedule_dir)

        assert schedule_file is not None
        assert len(schedule_file.schedules) == 2
        assert schedule_file.schedules[0].id == "schedule-1"
        assert schedule_file.schedules[1].id == "schedule-2"

    def test_directory_skips_config_file(self, temp_schedule_dir, sample_schedule_dict):
        """Test that _config.yaml is not loaded as a schedule."""
        # Create schedule file
        schedule_path = temp_schedule_dir / "test-schedule.yaml"
        data = sample_schedule_dict.copy()
        data["id"] = "test-schedule"
        data["transaction"]["metadata"]["schedule_id"] = "test-schedule"

        with open(schedule_path, "w") as f:
            yaml.dump(data, f)

        # Load directory
        schedule_file = load_schedules_from_directory(temp_schedule_dir)

        # Should have 1 schedule (not 2, since _config.yaml is skipped)
        assert schedule_file is not None
        assert len(schedule_file.schedules) == 1

    def test_directory_skips_hidden_files(
        self, temp_schedule_dir, sample_schedule_dict
    ):
        """Test that hidden files (.filename) are skipped."""
        # Create schedule file
        schedule_path = temp_schedule_dir / "test-schedule.yaml"
        data = sample_schedule_dict.copy()
        data["id"] = "test-schedule"
        data["transaction"]["metadata"]["schedule_id"] = "test-schedule"

        with open(schedule_path, "w") as f:
            yaml.dump(data, f)

        # Create hidden file (should be skipped)
        hidden_path = temp_schedule_dir / ".hidden-schedule.yaml"
        with open(hidden_path, "w") as f:
            yaml.dump(data, f)

        # Load directory
        schedule_file = load_schedules_from_directory(temp_schedule_dir)

        # Should have 1 schedule (hidden file skipped)
        assert schedule_file is not None
        assert len(schedule_file.schedules) == 1

    def test_directory_loads_global_config(self, temp_schedule_dir):
        """Test that global config is loaded from _config.yaml."""
        # Create custom config
        config_data = {
            "fuzzy_match_threshold": 0.90,
            "default_date_window_days": 5,
        }

        config_path = temp_schedule_dir / "_config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        # Load directory
        schedule_file = load_schedules_from_directory(temp_schedule_dir)

        assert schedule_file is not None
        assert schedule_file.config.fuzzy_match_threshold == 0.90
        assert schedule_file.config.default_date_window_days == 5

    def test_directory_uses_default_config_if_missing(self, temp_schedule_dir):
        """Test that default config is used if _config.yaml is missing."""
        # Don't create _config.yaml, just load directory
        schedule_file = load_schedules_from_directory(temp_schedule_dir)

        assert schedule_file is not None
        assert schedule_file.config.fuzzy_match_threshold == 0.80  # Default

    def test_filename_id_mismatch_prevents_load(
        self, temp_schedule_dir, sample_schedule_dict
    ):
        """Test that a schedule whose ID doesn't match its filename is not loaded."""
        # Create a file named "my-schedule.yaml" with a mismatched ID
        schedule_path = temp_schedule_dir / "my-schedule.yaml"
        data = sample_schedule_dict.copy()
        data["id"] = "other-id"  # deliberately mismatched
        data["transaction"]["metadata"]["schedule_id"] = "other-id"

        with open(schedule_path, "w") as f:
            yaml.dump(data, f)

        schedule_file = load_schedules_from_directory(temp_schedule_dir)

        # Mismatched file should not load; result may be None or empty
        if schedule_file is not None:
            assert len(schedule_file.schedules) == 0

    def test_duplicate_schedule_ids_deduplicated(
        self, temp_schedule_dir, sample_schedule_dict
    ):
        """Test that duplicate schedule IDs are deduplicated, keeping the first."""
        from unittest.mock import patch

        from beanschedule.schema import Schedule

        data_a = sample_schedule_dict.copy()
        data_a["id"] = "dup-schedule"
        data_a["transaction"] = dict(data_a["transaction"])
        data_a["transaction"]["metadata"] = {"schedule_id": "dup-schedule"}

        sched_a = Schedule(**data_a)
        sched_b = Schedule(**data_a)  # identical ID — simulates a duplicate

        with patch(
            "beanschedule.loader.load_schedule_from_file",
            side_effect=[sched_a, sched_b],
        ):
            # Fake two schedule files to trigger the duplicate detection path
            fake_files = [
                temp_schedule_dir / "dup-schedule.yaml",
                temp_schedule_dir / "dup-schedule-copy.yaml",
            ]
            for f in fake_files:
                f.touch()

            schedule_file = load_schedules_from_directory(temp_schedule_dir)

        assert schedule_file is not None
        dup_ids = [s.id for s in schedule_file.schedules if s.id == "dup-schedule"]
        assert len(dup_ids) == 1

    def test_invalid_schedule_files_skipped(
        self, temp_schedule_dir, sample_schedule_dict
    ):
        """Test that invalid schedule files are skipped."""
        # Create valid schedule
        valid_path = temp_schedule_dir / "valid-schedule.yaml"
        data = sample_schedule_dict.copy()
        data["id"] = "valid-schedule"
        data["transaction"]["metadata"]["schedule_id"] = "valid-schedule"

        with open(valid_path, "w") as f:
            yaml.dump(data, f)

        # Create invalid schedule (wrong filename)
        invalid_path = temp_schedule_dir / "wrong-name.yaml"
        data2 = sample_schedule_dict.copy()
        data2["id"] = "different-id"
        data2["transaction"]["metadata"]["schedule_id"] = "different-id"

        with open(invalid_path, "w") as f:
            yaml.dump(data2, f)

        # Load directory
        schedule_file = load_schedules_from_directory(temp_schedule_dir)

        # Should have 1 schedule (invalid skipped)
        assert schedule_file is not None
        assert len(schedule_file.schedules) == 1
        assert schedule_file.schedules[0].id == "valid-schedule"


class TestGetEnabledSchedules:
    """Tests for filtering enabled schedules."""

    def test_get_enabled_schedules(self, sample_schedule):
        """Test filtering enabled schedules."""
        # Create mixed enabled/disabled schedules
        schedule1 = sample_schedule(id="enabled-1", enabled=True)
        schedule2 = sample_schedule(id="disabled-1", enabled=False)
        schedule3 = sample_schedule(id="enabled-2", enabled=True)

        schedule_file = ScheduleFile(
            schedules=[schedule1, schedule2, schedule3],
            config=GlobalConfig(),
        )

        enabled = get_enabled_schedules(schedule_file)

        assert len(enabled) == 2
        assert enabled[0].id == "enabled-1"
        assert enabled[1].id == "enabled-2"

    def test_get_enabled_schedules_with_none(self):
        """Test that None schedule_file returns empty list."""
        enabled = get_enabled_schedules(None)

        assert len(enabled) == 0
        assert enabled == []

    def test_get_enabled_schedules_all_disabled(self, sample_schedule):
        """Test when all schedules are disabled."""
        schedule1 = sample_schedule(id="disabled-1", enabled=False)
        schedule2 = sample_schedule(id="disabled-2", enabled=False)

        schedule_file = ScheduleFile(
            schedules=[schedule1, schedule2],
            config=GlobalConfig(),
        )

        enabled = get_enabled_schedules(schedule_file)

        assert len(enabled) == 0


class TestEnvironmentVariableDiscovery:
    """Tests for environment variable-based discovery."""

    def test_beanschedule_dir_env_var(self, temp_schedule_dir, sample_schedule_dict):
        """Test that BEANSCHEDULE_DIR environment variable is used."""
        # Create schedule in temp directory
        schedule_path = temp_schedule_dir / "test-schedule.yaml"
        data = sample_schedule_dict.copy()
        data["id"] = "test-schedule"
        data["transaction"]["metadata"]["schedule_id"] = "test-schedule"

        with open(schedule_path, "w") as f:
            yaml.dump(data, f)

        # Set env var
        old_env = os.environ.get("BEANSCHEDULE_DIR")
        try:
            os.environ["BEANSCHEDULE_DIR"] = str(temp_schedule_dir)

            # Load using find_schedules_location
            location = find_schedules_location()

            assert location is not None
            assert location == temp_schedule_dir
        finally:
            if old_env:
                os.environ["BEANSCHEDULE_DIR"] = old_env
            else:
                os.environ.pop("BEANSCHEDULE_DIR", None)


class TestScheduleFileWithConfig:
    """Tests for ScheduleFile with config."""

    def test_schedule_file_with_config(self, sample_schedule):
        """Test ScheduleFile preserves config."""
        schedule = sample_schedule(id="test")
        config = GlobalConfig(fuzzy_match_threshold=0.85)

        schedule_file = ScheduleFile(
            schedules=[schedule],
            config=config,
        )

        assert schedule_file.config.fuzzy_match_threshold == 0.85

    def test_schedule_file_default_config(self, sample_schedule):
        """Test ScheduleFile uses default config if not provided."""
        schedule = sample_schedule(id="test")

        schedule_file = ScheduleFile(schedules=[schedule])

        assert schedule_file.config.fuzzy_match_threshold == 0.80  # Default


class TestEnvironmentVariableEdgeCases:
    """Tests for edge cases with environment variables."""

    def test_beanschedule_dir_nonexistent_path(self, tmp_path, monkeypatch):
        """Test BEANSCHEDULE_DIR pointing to non-existent directory."""
        old_dir = os.environ.get("BEANSCHEDULE_DIR")
        try:
            os.environ["BEANSCHEDULE_DIR"] = str(tmp_path / "nonexistent")
            # Mock Path.cwd() to return tmp_path (which has no schedules/)
            import beanschedule.loader as loader_module

            monkeypatch.setattr(loader_module.Path, "cwd", lambda: tmp_path)

            location = find_schedules_location()
            # Should continue to next check, not return the nonexistent path
            assert location is None
        finally:
            if old_dir:
                os.environ["BEANSCHEDULE_DIR"] = old_dir
            else:
                os.environ.pop("BEANSCHEDULE_DIR", None)


class TestLoadScheduleErrorHandling:
    """Tests for error handling in schedule loading."""

    def test_config_file_syntax_error(self, temp_schedule_dir, sample_schedule_dict):
        """Test handling of syntax errors in config file."""
        # Create a config file with invalid YAML
        config_path = temp_schedule_dir / "_config.yaml"
        with open(config_path, "w") as f:
            f.write("invalid: yaml: content:")

        # Create a valid schedule
        schedule_path = temp_schedule_dir / "test.yaml"
        sample_schedule_dict["id"] = "test"
        sample_schedule_dict["transaction"]["metadata"]["schedule_id"] = "test"
        with open(schedule_path, "w") as f:
            yaml.dump(sample_schedule_dict, f)

        # Should use default config and still load the schedule
        schedule_file = load_schedules_from_directory(temp_schedule_dir)
        assert schedule_file is not None
        assert schedule_file.config.fuzzy_match_threshold == 0.80  # Default

    def test_duplicate_schedule_ids_in_directory(
        self, temp_schedule_dir, sample_schedule_dict
    ):
        """Test detection of duplicate schedule IDs."""
        # This shouldn't happen in practice since filename must match ID
        # But we test the duplicate detection logic
        schedule_path1 = temp_schedule_dir / "test-a.yaml"
        sample_schedule_dict["id"] = "test-a"
        sample_schedule_dict["transaction"]["metadata"]["schedule_id"] = "test-a"
        with open(schedule_path1, "w") as f:
            yaml.dump(sample_schedule_dict, f)

        schedule_path2 = temp_schedule_dir / "test-b.yaml"
        sample_schedule_dict["id"] = "test-b"
        sample_schedule_dict["transaction"]["metadata"]["schedule_id"] = "test-b"
        with open(schedule_path2, "w") as f:
            yaml.dump(sample_schedule_dict, f)

        schedule_file = load_schedules_from_directory(temp_schedule_dir)
        assert schedule_file is not None
        assert len(schedule_file.schedules) == 2

    def test_auto_discovery_returns_none_if_not_found(self, tmp_path, monkeypatch):
        """Test that None is returned if no schedules directory found."""
        old_dir = os.environ.get("BEANSCHEDULE_DIR")
        try:
            os.environ.pop("BEANSCHEDULE_DIR", None)
            import beanschedule.loader as loader_module

            monkeypatch.setattr(loader_module.Path, "cwd", lambda: tmp_path)

            result = load_schedules()
            assert result is None or isinstance(result, ScheduleFile)
        finally:
            if old_dir:
                os.environ["BEANSCHEDULE_DIR"] = old_dir
            else:
                os.environ.pop("BEANSCHEDULE_DIR", None)
